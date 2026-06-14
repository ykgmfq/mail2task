"""Ollama preprocessing.

Turns a raw email into structured Todoist fields: a concise actionable title
and an optional ISO deadline. Uses Ollama with structured JSON output. Any
error falls back to the raw subject so mail is never dropped.
"""

import logging
from datetime import date

import ollama
from pydantic import BaseModel, field_validator

from .mail import Email

log = logging.getLogger(__name__)

BODY_LIMIT = 4000  # chars of body sent to the model

SYSTEM = (
    "You convert emails into Todoist tasks. Return a concise imperative title "
    "and an ISO deadline date (YYYY-MM-DD) if the email implies one (else null). "
    "Today is {today}."
)


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


def enrich_with_ollama(client: ollama.Client, model: str, email: Email) -> TaskFields:
    """Ask Ollama for structured task fields; fall back to the raw subject on error."""
    try:
        resp = client.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM.format(today=date.today().isoformat()),
                },
                {
                    "role": "user",
                    "content": (
                        f"From: {email.sender}\n"
                        f"Subject: {email.subject}\n\n"
                        f"{email.body[:BODY_LIMIT]}"
                    ),
                },
            ],
            format=TaskFields.model_json_schema(),
        )
        return TaskFields.model_validate_json(resp.message.content)
    except Exception:
        log.warning("Ollama enrichment failed; using raw subject", exc_info=True)
        return TaskFields(title=email.subject or "(no subject)", deadline=None)
