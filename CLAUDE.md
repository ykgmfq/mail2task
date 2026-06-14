# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**mail2task** is a long-running service that polls an IMAP folder, uses a local **Ollama** model to turn every email into a clean Todoist task, then marks the email seen and moves it to an archive folder.
For each email the model rewrites the subject into a concise actionable title and extracts an optional date.
The extracted date becomes the Todoist **deadline**; the task's **due date** is always set to today so it surfaces immediately for manual oversight, and the task carries a `mail2task` label.
A task gets the **highest priority when a deadline was found**, otherwise Todoist's default.
The sender and a body preview are set as the task's description.
The loop runs continuously, polling every `POLL_INTERVAL` seconds.

## Running

```bash
pip install -e .
POLL_INTERVAL=10 IMAP_HOST=... mail2task   # or: python -m mail2task
```

## Configuration

Config is read **only from the process environment** (`os.environ`); `.env.example` lists all keys.

Required: `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_ARCHIVE_FOLDER`, `TODOIST_API_TOKEN`, `OLLAMA_MODEL`.
Optional: `IMAP_PORT` (993), `OLLAMA_HOST` (`http://localhost:11434`), `TODOIST_PROJECT_NAME` (omit for inbox), `POLL_INTERVAL` (60).

`OLLAMA_MODEL` must be pulled into the Ollama server before starting (e.g. `ollama pull gemma4:e4b`).

## Conventions

**Human-facing text uses proper prose.**
This applies to markdown files, comments, log messages, and commit messages.
Write in full sentences, avoid terse shorthand, and prefer plain words over jargon.

**In markdown files, each sentence starts on its own line.**
This keeps git diffs clean — a change to one sentence only touches one line.

**The README is an abstract, not a manual.**
It should answer "what is this and why does it exist?" in a few sentences — enough for a reader to decide whether to go further.
Configuration details, installation steps, and usage instructions belong in the GitHub wiki, not the README.
When wiki content needs updating, write it into the ephemeral `wiki.md` file at the repo root; do not commit it.

**In GitHub Actions workflows, put longer `run:` blocks into shell script files.**
Keep one-liners inline.
Scripts live in `.github/scripts/` and are referenced from the workflow step.

**In shell scripts, avoid line continuations with backslash.**
Use intermediate variables instead.

## Deployment

- [Dockerfile](Dockerfile) — `python:3.14-alpine`, copies `pyproject.toml README.md LICENSE` + the package and runs `pip install .`, runs as a non-root user, `ENTRYPOINT ["mail2task"]`. (musllinux wheels exist for all deps, so no build toolchain is needed.)
- [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) — builds and pushes `ghcr.io/<owner>/mail2task` on push to `main` and on `v*` tags, using the built-in `GITHUB_TOKEN`.
- [docker-compose.yml](docker-compose.yml) — two-service stack (a local `ollama` plus `mail2task` built from the local Dockerfile); configuration is inline in the file. Models persist in the `ollama_data` volume.
- [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) — Python 3.14 devcontainer; `postCreateCommand` installs the package editable.
