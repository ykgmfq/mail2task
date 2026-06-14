"""Ollama preprocessing.

Turns a raw email into structured Todoist fields: a concise actionable title
and an optional ISO deadline. Uses Ollama with structured JSON output. Any
error falls back to the raw subject so mail is never dropped.
"""

import logging
from datetime import date

import ollama

from .models import Email, TaskFields

log = logging.getLogger(__name__)

BODY_LIMIT = 4000  # chars of body sent to the model

SYSTEM = (
    "You convert emails into Todoist tasks. Return a concise imperative title "
    "and an ISO deadline date (YYYY-MM-DD) if the email implies one (else null). "
    "Today is {today}."
)


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
