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

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DEFAULT_IMAP_TIMEOUT = 30  # seconds; a hung socket must not freeze the poll loop


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


def _decode_part(part) -> str:
    """Decode a single MIME part's payload to text, tolerating missing payloads.

    A declared charset may be empty or one Python does not know; fall back to
    utf-8 with replacement so a malformed header never crashes processing.
    """
    data = part.get_payload(decode=True)
    if not data:  # signed/empty/structural parts can decode to None
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    """Reduce HTML to readable plain text via a real parser (tolerant of malformed markup)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def get_text_body(msg) -> str:
    """Extract a plain-text body, preferring text/plain and falling back to HTML.

    Some messages carry only an HTML alternative; rather than yield an empty
    body, strip its tags so the model still has something to work with.
    """
    plain_parts = []
    html_parts = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        if "attachment" in str(part.get("Content-Disposition", "")):
            continue
        ct = part.get_content_type()
        if ct == "text/plain":
            plain_parts.append(_decode_part(part))
        elif ct == "text/html":
            html_parts.append(_decode_part(part))

    if any(p.strip() for p in plain_parts):
        return "\n".join(plain_parts).strip()
    if any(p.strip() for p in html_parts):
        return _html_to_text("\n".join(html_parts)).strip()
    return ""


@contextmanager
def connect(cfg: dict):
    """Open an authenticated IMAP4_SSL connection and select the target folder."""
    host = cfg["IMAP_HOST"]
    port = int(cfg.get("IMAP_PORT", 993))
    user = cfg["IMAP_USER"]
    folder = cfg["IMAP_FOLDER"]
    timeout = int(cfg.get("IMAP_TIMEOUT", DEFAULT_IMAP_TIMEOUT))

    log.info("Connecting to %s:%d as %s", host, port, user)
    with imaplib.IMAP4_SSL(host, port, timeout=timeout) as imap:
        imap.login(user, cfg["IMAP_PASSWORD"])
        status, _ = imap.select(f'"{folder}"')
        if status != "OK":
            raise RuntimeError(f"Could not select folder '{folder}'")
        yield imap


def iter_all(imap) -> Iterator[tuple[bytes, Email]]:
    """Yield (msg_id, Email) for every unseen message in the selected folder.

    Searching UNSEEN (rather than ALL) means a message whose archive failed
    after its task was created is not picked up again, so no duplicate task.
    """
    status, data = imap.search(None, "UNSEEN")
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
