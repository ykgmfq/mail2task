"""Orchestration: poll the mailbox, enrich, create tasks, and loop."""

import logging
import os
import signal
import sys
import threading

import ollama
from todoist_api_python.api import TodoistAPI

from . import mail
from .enrich import enrich_with_ollama
from .tasks import add_attachment_comments, build_comment, create_task

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    # No timestamp: the journal records the time of each line, so emitting our own would only duplicate it.
    format="%(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

REQUIRED_CONFIG = [
    "IMAP_HOST",
    "IMAP_USER",
    "IMAP_PASSWORD",
    "IMAP_FOLDER",
    "IMAP_ARCHIVE_FOLDER",
    "TODOIST_API_TOKEN",
    "OLLAMA_MODEL",
]

# Optional integer settings validated at startup so a typo fails fast and loud
# rather than crashing mid-cycle. Maps env var -> default.
INT_CONFIG = {
    "IMAP_PORT": 993,
    "IMAP_TIMEOUT": 30,
    "OLLAMA_TIMEOUT": 120,
    "POLL_INTERVAL": 60,
}


def load_config() -> dict:
    """Read configuration from environment variables. Exits if required keys are missing or invalid."""
    cfg = dict(os.environ)
    missing = [k for k in REQUIRED_CONFIG if not cfg.get(k)]
    if missing:
        sys.exit(f"Missing config keys: {', '.join(missing)}")
    for key, default in INT_CONFIG.items():
        raw = cfg.get(key)
        if raw in (None, ""):
            cfg[key] = str(default)
            continue
        try:
            int(raw)
        except ValueError:
            sys.exit(f"Config key {key} must be an integer, got: {raw!r}")
    return cfg


def resolve_project_id(todoist: TodoistAPI, cfg: dict) -> None:
    """Resolve TODOIST_PROJECT_NAME to an ID stored in cfg, or exit if not found."""
    name = cfg.get("TODOIST_PROJECT_NAME")
    if not name:
        return
    projects = [p for page in todoist.get_projects() for p in page]
    match = next((p for p in projects if p.name.casefold() == name.casefold()), None)
    if match is None:
        available = ", ".join(p.name for p in projects)
        sys.exit(f"Todoist project '{name}' not found. Available: {available}")
    cfg["TODOIST_PROJECT_ID"] = match.id
    log.info("Resolved project '%s' → %s", name, match.id)


def process_mailbox(cfg: dict, ollama_client: ollama.Client, model: str, todoist: TodoistAPI) -> None:
    """Process every message in the folder once."""
    archive_folder = cfg["IMAP_ARCHIVE_FOLDER"]
    any_archived = False
    with mail.connect(cfg) as imap:
        for msg_id, email in mail.iter_all(imap):
            try:
                log.info("Processing: %s (from %s)", email.subject, email.sender)
                fields = enrich_with_ollama(ollama_client, model, email)
                comment = build_comment(email)
                task_id = create_task(todoist, cfg, fields, comment)
                # Mark seen immediately so a failure below cannot re-create the
                # task next cycle; UNSEEN search then skips this message.
                mail.mark_seen(imap, msg_id)
                log.info("Created task %s: '%s'", task_id, fields.title)
                add_attachment_comments(todoist, cfg, task_id, email.attachments)
                mail.archive_message(imap, msg_id, archive_folder)
                any_archived = True
            except Exception:
                # One bad message must not abort the cycle.
                log.exception("Failed on message %s", msg_id)
        if any_archived:
            imap.expunge()


_MAX_BACKOFF_FACTOR = 10  # cap consecutive-failure backoff at 10x the interval


def main() -> None:
    cfg = load_config()
    ollama_client = ollama.Client(
        host=cfg.get("OLLAMA_HOST", "http://localhost:11434"),
        timeout=int(cfg["OLLAMA_TIMEOUT"]),
    )
    model = cfg["OLLAMA_MODEL"]
    todoist = TodoistAPI(cfg["TODOIST_API_TOKEN"])
    resolve_project_id(todoist, cfg)
    interval = int(cfg["POLL_INTERVAL"])

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # clean container shutdown
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    log.info("mail2task started; polling every %ds", interval)
    failures = 0
    while not stop.is_set():
        try:
            process_mailbox(cfg, ollama_client, model, todoist)
            failures = 0
        except Exception:
            # Survive transient IMAP / network errors; back off so a sustained
            # outage (e.g. Ollama down) does not hammer the dependency or logs.
            failures += 1
            log.exception("Poll cycle failed (%d in a row); will retry", failures)
        stop.wait(interval * min(failures + 1, _MAX_BACKOFF_FACTOR))
    log.info("mail2task stopped")


if __name__ == "__main__":
    main()
