"""Orchestration: poll the mailbox, enrich, create tasks, and loop."""

import logging
import os
import signal
import sys
import threading
from dataclasses import dataclass

import ollama
from pydantic import HttpUrl, ValidationError
from todoist_api_python.api import TodoistAPI

from . import mail
from .enrich import enrich_with_ollama
from .models import Config
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

# OLLAMA_HOST is a base URL; parse it to an HttpUrl at startup so a malformed
# value fails fast rather than surfacing as an opaque connection error mid-cycle.


def load_config() -> Config:
    """Read and validate configuration from the environment into a typed Config.

    Exits if a required key is missing or an integer setting does not parse, so a
    typo fails fast at startup rather than crashing mid-cycle.
    """
    env = os.environ
    missing = [k for k in REQUIRED_CONFIG if not env.get(k)]
    if missing:
        sys.exit(f"Missing config keys: {', '.join(missing)}")
    ints = {}
    for key, default in INT_CONFIG.items():
        raw = env.get(key)
        if raw in (None, ""):
            ints[key] = default
            continue
        try:
            ints[key] = int(raw)
        except ValueError:
            sys.exit(f"Config key {key} must be an integer, got: {raw!r}")
    raw_host = env.get("OLLAMA_HOST") or "http://localhost:11434"
    try:
        ollama_host = HttpUrl(raw_host)
    except ValidationError:
        sys.exit(f"Config key OLLAMA_HOST must be a valid URL, got: {raw_host!r}")
    return Config(
        imap_host=env["IMAP_HOST"],
        imap_user=env["IMAP_USER"],
        imap_password=env["IMAP_PASSWORD"],
        imap_folder=env["IMAP_FOLDER"],
        imap_archive_folder=env["IMAP_ARCHIVE_FOLDER"],
        todoist_api_token=env["TODOIST_API_TOKEN"],
        ollama_model=env["OLLAMA_MODEL"],
        imap_port=ints["IMAP_PORT"],
        imap_timeout=ints["IMAP_TIMEOUT"],
        ollama_timeout=ints["OLLAMA_TIMEOUT"],
        poll_interval=ints["POLL_INTERVAL"],
        ollama_host=ollama_host,
        todoist_project_name=env.get("TODOIST_PROJECT_NAME") or None,
    )


def resolve_project_id(todoist: TodoistAPI, name: str | None) -> str | None:
    """Resolve a Todoist project name to its id, or exit if it does not exist.

    Returns None when no project name is configured (tasks then land in the inbox).
    """
    if not name:
        return None
    projects = [p for page in todoist.get_projects() for p in page]
    match = next((p for p in projects if p.name.casefold() == name.casefold()), None)
    if match is None:
        available = ", ".join(p.name for p in projects)
        sys.exit(f"Todoist project '{name}' not found. Available: {available}")
    log.info("Resolved project '%s' → %s", name, match.id)
    return match.id


@dataclass(frozen=True)
class Context:
    """The runtime dependencies a poll cycle needs, bundled into one handle."""

    config: Config
    ollama: ollama.Client
    todoist: TodoistAPI
    project_id: str | None


def process_mailbox(ctx: Context) -> None:
    """Process every message in the folder once."""
    any_archived = False
    with mail.connect(ctx.config) as imap:
        for msg_id, email in mail.iter_all(imap):
            try:
                log.info("Processing: %s (from %s)", email.subject, email.sender)
                fields = enrich_with_ollama(ctx.ollama, ctx.config.ollama_model, email)
                comment = build_comment(email)
                task_id = create_task(ctx.todoist, ctx.project_id, fields, comment)
                # Mark seen immediately so a failure below cannot re-create the
                # task next cycle; UNSEEN search then skips this message.
                mail.mark_seen(imap, msg_id)
                log.info("Created task %s: '%s'", task_id, fields.title)
                add_attachment_comments(ctx.todoist, ctx.config.todoist_api_token, task_id, email.attachments)
                mail.archive_message(imap, msg_id, ctx.config.imap_archive_folder)
                any_archived = True
            except Exception:
                # One bad message must not abort the cycle.
                log.exception("Failed on message %s", msg_id)
        if any_archived:
            imap.expunge()


_MAX_BACKOFF_FACTOR = 10  # cap consecutive-failure backoff at 10x the interval


def poll_loop(ctx: Context, stop: threading.Event, interval: int) -> None:
    """Poll the mailbox until stop is set, backing off on consecutive failures."""
    failures = 0
    while not stop.is_set():
        try:
            process_mailbox(ctx)
            failures = 0
        except Exception:
            # Survive transient IMAP / network errors; back off so a sustained
            # outage (e.g. Ollama down) does not hammer the dependency or logs.
            failures += 1
            log.exception("Poll cycle failed (%d in a row); will retry", failures)
        stop.wait(interval * min(failures + 1, _MAX_BACKOFF_FACTOR))


def main() -> None:
    config = load_config()
    ollama_client = ollama.Client(host=str(config.ollama_host), timeout=config.ollama_timeout)
    todoist = TodoistAPI(config.todoist_api_token)
    project_id = resolve_project_id(todoist, config.todoist_project_name)
    ctx = Context(config=config, ollama=ollama_client, todoist=todoist, project_id=project_id)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # clean container shutdown
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    log.info("mail2task started; polling every %ds", config.poll_interval)
    poll_loop(ctx, stop, config.poll_interval)
    log.info("mail2task stopped")


if __name__ == "__main__":
    main()
