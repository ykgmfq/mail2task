# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**mail2task** is a long-running service that polls an IMAP folder, uses a local **Ollama** model to turn every email into a clean Todoist task, then marks the email seen and moves it to an archive folder. For each email the model rewrites the subject into a concise actionable title and extracts an optional date. The extracted date becomes the Todoist **deadline**; the task's **due date** is always set to today so it surfaces immediately for manual oversight, and the task carries a `mail2task` label. A task gets **priority 2 when a deadline was found**, otherwise Todoist's default. The sender and a body preview are attached as a Todoist comment. The loop runs continuously, polling every `POLL_INTERVAL` seconds.

## Running

```bash
# Install (editable)
pip install -e .

# Run (config from the environment)
POLL_INTERVAL=10 IMAP_HOST=... mail2task
# or: python -m mail2task
```

Container:

```bash
docker build -t mail2task .
docker run --rm --env-file .env mail2task   # needs OLLAMA_HOST pointing at a reachable Ollama
# or run the full stack (bundles a local Ollama, config inline): docker compose up --build
```

## Configuration

Config is read **only from the process environment** (`os.environ`). Locally, export the vars or use `docker run --env-file` / `docker-compose.yml`; `.env.example` lists them.

Required keys: `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_ARCHIVE_FOLDER` (processed mail is moved here — mandatory, since every message in the folder is processed each cycle), `TODOIST_API_TOKEN`, `OLLAMA_MODEL`.
Optional: `IMAP_PORT` (993), `OLLAMA_HOST` (`http://localhost:11434`), `TODOIST_PROJECT_NAME` (name of the Todoist project; omit to use inbox), `POLL_INTERVAL` (60).

`OLLAMA_MODEL` must already be pulled into the Ollama server at `OLLAMA_HOST` (e.g. `ollama pull gemma4:e4b`); the compose stack runs a local Ollama and persists models in the `ollama_data` volume.

## Architecture

A `mail2task/` package, one module per concern:

- [mail.py](mail2task/mail.py) — all IMAP/MIME concerns. `connect()` (context manager, per-cycle `IMAP4_SSL`), `iter_all()` yields `(msg_id, Email)`, `mark_seen()`, `archive_message()` (copy + delete; caller expunges after the loop). Holds the `decode_header_value` / `get_text_body` helpers and the `Email` dataclass.
- [enrich.py](mail2task/enrich.py) — `enrich_with_ollama()`: calls `ollama.Client.chat` with a JSON-schema `format` derived from the `TaskFields` Pydantic model (`title` + optional ISO `deadline`; no model-chosen priority). On any `Exception` it falls back to the raw subject so mail is never dropped.
- [tasks.py](mail2task/tasks.py) — `create_task()` / `build_comment()` / `add_attachment_comments()` over the official `todoist-api-python` SDK (`add_task` + `add_comment` + file uploads). `create_task` sets `due_date=today`, `deadline_date=<extracted>`, `priority=2` when a deadline exists (else default), and the `mail2task` label.
- [app.py](mail2task/app.py) — `load_config()` (reads/validates env vars), `resolve_project_id()` (maps `TODOIST_PROJECT_NAME` → id), `process_mailbox()` orchestrates one cycle (enrich → create labelled task → mark seen → archive, with per-message error isolation), and `main()` is the polling loop with SIGTERM/SIGINT handling for clean container shutdown.
- [__main__.py](mail2task/__main__.py) — `python -m mail2task` entry. Console script `mail2task` → `mail2task.app:main` (declared in [pyproject.toml](pyproject.toml)).

Key invariants: a message is marked seen and archived **only after** its task is created; a single failing message is logged and skipped without aborting the cycle; a failing poll cycle is logged and retried on the next tick.

## Deployment

- [Dockerfile](Dockerfile) — `python:3.14-alpine`, copies `pyproject.toml README.md LICENSE` + the package and runs `pip install .`, runs as a non-root user, `ENTRYPOINT ["mail2task"]`. (musllinux wheels exist for all deps, so no build toolchain is needed.)
- [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) — builds and pushes `ghcr.io/<owner>/mail2task` on push to `main` and on `v*` tags, using the built-in `GITHUB_TOKEN`.
- [docker-compose.yml](docker-compose.yml) — two-service stack (a local `ollama` plus `mail2task` built from the local Dockerfile); configuration is inline in the file. Models persist in the `ollama_data` volume.
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) — Python 3.14 devcontainer; `postCreateCommand` installs the package editable.
