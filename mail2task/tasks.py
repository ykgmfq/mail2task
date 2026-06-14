"""Todoist task creation via the official todoist-api-python SDK."""

import logging
from datetime import date

import requests
from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Attachment

from .models import Email, EmailAttachment, TaskFields

log = logging.getLogger(__name__)

_UPLOAD_URL = "https://api.todoist.com/api/v1/uploads"
_LABEL = "mail2task"
_UPLOAD_TIMEOUT = 60  # seconds; never block the loop on a stalled upload


def build_description(email: Email) -> str:
    """Build the task description: sender plus a truncated body preview."""
    parts = [f"**From:** {email.sender}"]
    if email.body:
        preview = email.body[:2000]
        if len(email.body) > 2000:
            preview += "\n\n*(truncated)*"
        parts.append(f"\n---\n{preview}")
    return "\n".join(parts)


def _upload_file(api_token: str, att: EmailAttachment) -> Attachment:
    """Upload a file to Todoist and return an SDK Attachment object."""
    resp = requests.post(
        _UPLOAD_URL,
        headers={"Authorization": f"Bearer {api_token}"},
        files={"file": (att.filename, att.data, att.content_type)},
        timeout=_UPLOAD_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return Attachment(
        resource_type="file",
        file_name=data["file_name"],
        file_url=data["file_url"],
        file_type=data["file_type"],
        file_size=data.get("file_size"),
    )


def add_attachment_comments(
    api: TodoistAPI, api_token: str, task_id: str, attachments: list[EmailAttachment]
) -> None:
    """Upload each email attachment and post it as a comment on the task."""
    for att in attachments:
        try:
            todoist_att = _upload_file(api_token, att)
            api.add_comment(att.filename, task_id=task_id, attachment=todoist_att)
            log.info("Attached '%s' to task %s", att.filename, task_id)
        except Exception:
            log.warning("Failed to attach '%s'", att.filename, exc_info=True)


def create_task(api: TodoistAPI, project_id: str | None, fields: TaskFields, description: str) -> str:
    """Create a Todoist task carrying the sender and body preview as its description; return the new task id."""
    deadline = date.fromisoformat(fields.deadline) if fields.deadline else None
    task = api.add_task(
        fields.title,
        description=description,  # sender and body preview, shown under the title
        project_id=project_id or None,
        # Flag deadline-bearing tasks with the API's highest priority; else
        # default. The API scale is inverted from the UI (4 is urgent, 1 is
        # normal), so the elevated value is 4.
        priority=4 if deadline else None,
        due_date=date.today(),  # surface today for manual oversight
        deadline_date=deadline,  # the date extracted from the email, if any
        labels=[_LABEL],
    )
    return task.id
