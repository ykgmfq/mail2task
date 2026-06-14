# mail2task package

## Architecture

One module per concern:

- [models.py](models.py) — the package's data structures, with no I/O: the `Email` / `EmailAttachment` dataclasses, the `TaskFields` Pydantic model (`title` + optional ISO `deadline`; a field validator drops a `deadline` that is malformed or already in the past), and the typed, frozen `Config` dataclass (required keys plus the optional ones with their defaults; integers already parsed). Keeping the shapes here separates what the data *is* from the logic that fetches, enriches, and stores it.
- [mail.py](mail.py) — all IMAP/MIME concerns. `connect(config)` (context manager, per-cycle `IMAP4_SSL` with a socket timeout, reads its host/port/credentials from the `Config`), `iter_all()` searches `UNSEEN` and yields `(msg_id, Email)`, `mark_seen()`, `archive_message()` (copy + delete; caller expunges after the loop). Holds the `decode_header_value` / `get_text_body` helpers (the latter prefers `text/plain`, falls back to tag-stripped `text/html`, and tolerates empty payloads).
- [enrich.py](enrich.py) — `enrich_with_ollama()`: calls `ollama.Client.chat` with a JSON-schema `format` derived from the `TaskFields` model (no model-chosen priority). On any `Exception` it falls back to the raw subject so mail is never dropped.
- [tasks.py](tasks.py) — `create_task()` / `build_description()` / `add_attachment_comments()` over the official `todoist-api-python` SDK (`add_task` + `add_comment` + file uploads). These take only what they need (`project_id`, `api_token`) rather than the whole config. `create_task` carries the sender and body preview as the task `description`, and sets `due_date=today`, `deadline_date=<extracted>`, `priority=4` (the API's highest; the scale is inverted from the UI) when a deadline exists (else default), and the `mail2task` label.
- [app.py](app.py) — orchestration. `load_config()` reads/validates env vars and returns a `Config`; `resolve_project_id()` is pure (maps a project name → id, or `None`); the frozen `Context` bundles the per-cycle dependencies (`config`, `ollama`, `todoist`, `project_id`); `process_mailbox(ctx)` orchestrates one cycle (enrich → create labelled task → mark seen → attach → archive, with per-message error isolation); `poll_loop(ctx, stop, interval)` is the worker loop with exponential backoff on consecutive cycle failures; and `main()` does wiring only — load config, build clients, resolve the project, install SIGTERM/SIGINT handlers for clean container shutdown, then run `poll_loop`.
- [__main__.py](__main__.py) — `python -m mail2task` entry. Console script `mail2task` → `mail2task.app:main` (declared in [pyproject.toml](../pyproject.toml)).

Key invariants: a message's task is created **before** it is marked seen, and it is marked seen **before** attachments and archiving, so a failure after creation can never produce a duplicate task (the next cycle's `UNSEEN` search skips it); a single failing message is logged and skipped without aborting the cycle; a failing poll cycle is logged and retried with backoff on the next tick.

## Code conventions

**Never silently discard exceptions.**
Always let exceptions propagate or log-and-re-raise with context.
The only deliberate catch-alls are the two isolation boundaries already established: per-message errors in `process_mailbox()` and per-cycle errors in `poll_loop()`, both of which log before continuing.

**Favour functional style; keep functions pure.**
Functions should compute and return results from their inputs without side effects.
Avoid mutating arguments, relying on module-level state, or mixing I/O with logic.
Where side effects are unavoidable (network calls, IMAP commands), isolate them at the call site rather than burying them inside logic functions.

**In comments and agent instructions, state intent and rationale — the *why* — not mechanics.**
Mechanics duplicated in prose drift out of sync with the code, so let the code be the source of truth.
