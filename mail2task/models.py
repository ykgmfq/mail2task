"""Data structures shared across the package: no I/O, just shapes and validation.

Keeping the models here separates what the data *is* from the logic that fetches,
enriches, and stores it, so each concern module ([mail.py](mail.py),
[enrich.py](enrich.py), [tasks.py](tasks.py), [app.py](app.py)) imports its shapes
from one place.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, HttpUrl, field_validator

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


class TaskFields(BaseModel):
    title: str  # short, imperative, actionable
    deadline: str | None  # ISO YYYY-MM-DD, or None

    @field_validator("deadline")
    @classmethod
    def _drop_unusable_deadline(cls, value: str | None) -> str | None:
        """Discard a deadline the model returned that is malformed or already past.

        The model occasionally invents a date or emits a non-ISO string; a bad
        value here would otherwise crash task creation, so we drop it rather than
        let it through.
        """
        if not value:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            log.warning("Ignoring malformed deadline from model: %r", value)
            return None
        if parsed < date.today():
            log.warning("Ignoring past deadline from model: %s", value)
            return None
        return value


@dataclass(frozen=True)
class Config:
    """Validated configuration, parsed once from the environment at startup.

    Required keys have no default; the optional ones carry the documented defaults.
    Integer settings are parsed to ``int`` here so the rest of the code never
    re-parses them.
    """

    imap_host: str
    imap_user: str
    imap_password: str
    imap_folder: str
    imap_archive_folder: str
    todoist_api_token: str
    ollama_model: str
    imap_port: int = 993
    imap_timeout: int = 30
    ollama_timeout: int = 600
    poll_interval: int = 60
    ollama_host: HttpUrl = HttpUrl("http://localhost:11434")
    todoist_project_name: str | None = None
