"""Tests for the IMAP/MIME parsing helpers in mail2task.mail."""

import email

from mail2task import mail


def _message(raw: str):
    return email.message_from_bytes(raw.encode("utf-8"))


def test_decode_header_value_plain():
    assert mail.decode_header_value("Hello there") == "Hello there"


def test_decode_header_value_encoded():
    # RFC 2047 encoded-word with a non-ASCII character.
    assert mail.decode_header_value("=?utf-8?b?w6RiYw==?=") == "äbc"


def test_decode_header_value_none():
    assert mail.decode_header_value(None) == ""


def test_get_text_body_plain():
    msg = _message(
        "Subject: x\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nhello body\r\n"
    )
    assert mail.get_text_body(msg) == "hello body"


def test_get_text_body_multipart_prefers_plain():
    raw = (
        "Subject: x\r\n"
        'Content-Type: multipart/alternative; boundary="b"\r\n\r\n'
        "--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nplain wins\r\n"
        "--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>html</p>\r\n"
        "--b--\r\n"
    )
    assert mail.get_text_body(_message(raw)) == "plain wins"


def test_get_text_body_html_fallback():
    raw = (
        "Subject: x\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>Hello</p><br><b>world</b> &amp; more</body></html>\r\n"
    )
    body = mail.get_text_body(_message(raw))
    assert "Hello" in body
    assert "world" in body
    assert "& more" in body
    assert "<" not in body  # tags stripped


def test_get_text_body_html_drops_script_and_style():
    raw = (
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<style>p{color:red}</style><script>alert(1)</script><p>keep</p>"
    )
    body = mail.get_text_body(_message(raw))
    assert "keep" in body
    assert "alert" not in body
    assert "color" not in body


def test_get_text_body_empty_payload():
    # A bare structural part with no payload must not raise.
    raw = "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    assert mail.get_text_body(_message(raw)) == ""


def test_get_text_body_bad_charset_does_not_raise():
    raw = (
        "Content-Type: text/plain; charset=definitely-not-a-charset\r\n\r\n"
        "still readable\r\n"
    )
    assert mail.get_text_body(_message(raw)) == "still readable"


def test_get_attachments():
    raw = (
        "Subject: x\r\n"
        'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        "--b\r\nContent-Type: text/plain\r\n\r\nbody\r\n"
        "--b\r\nContent-Type: text/plain\r\n"
        'Content-Disposition: attachment; filename="note.txt"\r\n\r\n'
        "file contents\r\n"
        "--b--\r\n"
    )
    atts = mail.get_attachments(_message(raw))
    assert len(atts) == 1
    assert atts[0].filename == "note.txt"
    assert atts[0].data == b"file contents"


class _FakeIMAP:
    """Records the SEARCH criteria and serves a single fetchable message."""

    def __init__(self):
        self.search_args = None

    def search(self, charset, criteria):
        self.search_args = criteria
        return "OK", [b"1"]

    def fetch(self, msg_id, spec):
        raw = b"Subject: hi\r\nFrom: Alice <a@example.com>\r\n\r\nbody"
        return "OK", [(b"1 (RFC822)", raw)]


def test_iter_all_searches_unseen():
    imap = _FakeIMAP()
    results = list(mail.iter_all(imap))
    assert imap.search_args == "UNSEEN"
    assert len(results) == 1
    _, parsed = results[0]
    assert parsed.subject == "hi"
    assert "a@example.com" in parsed.sender
