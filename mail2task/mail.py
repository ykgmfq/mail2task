"""IMAP access: connect, iterate all messages, mark them seen, archive them.

All IMAP and MIME-decoding concerns live here. A fresh connection is opened per
poll cycle (robust against dropped sockets), exposed via the ``connect`` context
manager so the caller can mark and move messages on the live handle.
"""

import email
import email.header
import imaplib
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass
class EmailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class Email:
    subject: str
    sender: str  # display name + address, decoded
    body: str
    attachments: list[EmailAttachment] = field(default_factory=list)


def decode_header_value(raw) -> str:
    """Decode a possibly encoded email header value to a plain string."""
    parts = email.header.decode_header(raw or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded).strip()


def get_attachments(msg) -> list[EmailAttachment]:
    """Extract file attachments from an email.Message."""
    result = []
    for part in msg.walk():
        if "attachment" in str(part.get("Content-Disposition", "")):
            filename = decode_header_value(part.get_filename() or "attachment")
            data = part.get_payload(decode=True)
            if data:
                result.append(EmailAttachment(
                    filename=filename,
                    content_type=part.get_content_type(),
                    data=data,
                ))
    return result


def get_text_body(msg) -> str:
    """Extract plain-text body from an email.Message, handling multipart."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace").strip()
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return msg.get_payload(decode=True).decode(charset, errors="replace").strip()


@contextmanager
def connect(cfg: dict):
    """Open an authenticated IMAP4_SSL connection and select the target folder."""
    host = cfg["IMAP_HOST"]
    port = int(cfg.get("IMAP_PORT", 993))
    user = cfg["IMAP_USER"]
    folder = cfg["IMAP_FOLDER"]

    log.info("Connecting to %s:%d as %s", host, port, user)
    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, cfg["IMAP_PASSWORD"])
        status, _ = imap.select(f'"{folder}"')
        if status != "OK":
            raise RuntimeError(f"Could not select folder '{folder}'")
        yield imap


def iter_all(imap) -> Iterator[tuple[bytes, Email]]:
    """Yield (msg_id, Email) for every message in the selected folder."""
    status, data = imap.search(None, "ALL")
    if status != "OK":
        raise RuntimeError("IMAP SEARCH command failed")

    ids = data[0].split()
    if not ids:
        log.info("No messages")
        return

    log.info("Found %d message(s)", len(ids))
    for msg_id in ids:
        status, msg_data = imap.fetch(msg_id, "(RFC822)")
        if status != "OK":
            log.warning("Could not fetch message %s", msg_id)
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        from_raw = msg.get("From", "")
        _, sender_addr = parseaddr(from_raw)
        yield msg_id, Email(
            subject=decode_header_value(msg.get("Subject", "(no subject)")),
            sender=decode_header_value(from_raw) or sender_addr,
            body=get_text_body(msg),
            attachments=get_attachments(msg),
        )


def mark_seen(imap, msg_id: bytes) -> None:
    """Flag a message as seen so it is not processed again."""
    imap.store(msg_id, "+FLAGS", "\\Seen")


def archive_message(imap, msg_id: bytes, archive_folder: str) -> None:
    """Copy message to archive_folder and mark the original deleted.

    Call imap.expunge() after the processing loop — not here — to avoid
    sequence-number shifts for messages still to be processed this cycle.
    """
    status, _ = imap.copy(msg_id, f'"{archive_folder}"')
    if status != "OK":
        raise RuntimeError(f"Could not copy message {msg_id} to '{archive_folder}'")
    imap.store(msg_id, "+FLAGS", "\\Deleted")
