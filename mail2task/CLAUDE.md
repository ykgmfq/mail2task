# mail2task package

## Architecture

One module per concern:

- [mail.py](mail.py) — all IMAP/MIME concerns. `connect()` (context manager, per-cycle `IMAP4_SSL` with a socket timeout), `iter_all()` searches `UNSEEN` and yields `(msg_id, Email)`, `mark_seen()`, `archive_message()` (copy + delete; caller expunges after the loop). Holds the `decode_header_value` / `get_text_body` helpers (the latter prefers `text/plain`, falls back to tag-stripped `text/html`, and tolerates empty payloads) and the `Email` dataclass.
- [enrich.py](enrich.py) — `enrich_with_ollama()`: calls `ollama.Client.chat` with a JSON-schema `format` derived from the `TaskFields` Pydantic model (`title` + optional ISO `deadline`; no model-chosen priority). A field validator drops a `deadline` that is malformed or already in the past. On any `Exception` it falls back to the raw subject so mail is never dropped.
- [tasks.py](tasks.py) — `create_task()` / `build_comment()` / `add_attachment_comments()` over the official `todoist-api-python` SDK (`add_task` + `add_comment` + file uploads). `create_task` sets `due_date=today`, `deadline_date=<extracted>`, `priority=2` when a deadline exists (else default), and the `mail2task` label.
- [app.py](app.py) — `load_config()` (reads/validates env vars, including that the optional integer settings parse), `resolve_project_id()` (maps `TODOIST_PROJECT_NAME` → id), `process_mailbox()` orchestrates one cycle (enrich → create labelled task → mark seen → attach → archive, with per-message error isolation), and `main()` is the polling loop with SIGTERM/SIGINT handling for clean container shutdown and exponential backoff on consecutive cycle failures.
- [__main__.py](__main__.py) — `python -m mail2task` entry. Console script `mail2task` → `mail2task.app:main` (declared in [pyproject.toml](../pyproject.toml)).

Key invariants: a message's task is created **before** it is marked seen, and it is marked seen **before** attachments and archiving, so a failure after creation can never produce a duplicate task (the next cycle's `UNSEEN` search skips it); a single failing message is logged and skipped without aborting the cycle; a failing poll cycle is logged and retried with backoff on the next tick.

## Code conventions

**Never silently discard exceptions.**
Always let exceptions propagate or log-and-re-raise with context.
The only deliberate catch-alls are the two isolation boundaries already established: per-message errors in `process_mailbox()` and per-cycle errors in `main()`, both of which log before continuing.

**Favour functional style; keep functions pure.**
Functions should compute and return results from their inputs without side effects.
Avoid mutating arguments, relying on module-level state, or mixing I/O with logic.
Where side effects are unavoidable (network calls, IMAP commands), isolate them at the call site rather than burying them inside logic functions.

**In comments and agent instructions, state intent and rationale — the *why* — not mechanics.**
Mechanics duplicated in prose drift out of sync with the code, so let the code be the source of truth.
