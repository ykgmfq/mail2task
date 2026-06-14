# mail2task

Turn incoming email into Todoist tasks. mail2task polls an IMAP folder and, for
each message, asks a local **Ollama** model to write a clean, actionable task
title and pull out a deadline. Every task is dated **today** (so it surfaces for
review), tagged with a `mail2task` label, and carries the original sender and a
body preview as a comment. The processed message is then moved to an archive
folder so it's never handled twice. It runs continuously, checking for mail on a
fixed interval.

## What you need

- An **IMAP mailbox** (host, username, password). For Gmail/Outlook use an
  app-specific password.
- A **Todoist API token** — Todoist → Settings → Integrations → Developer.
- An **Ollama server** with a model pulled. The bundled
  [docker-compose.yml](docker-compose.yml) runs one for you; just pull a model
  into it, e.g. `ollama pull gemma4:e4b`.

## Configuration

mail2task is configured entirely through environment variables.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `IMAP_HOST` | ✅ | — | IMAP server hostname |
| `IMAP_USER` | ✅ | — | IMAP username |
| `IMAP_PASSWORD` | ✅ | — | IMAP password (use an app password) |
| `IMAP_FOLDER` | ✅ | — | Folder to watch, e.g. `Todo` |
| `IMAP_ARCHIVE_FOLDER` | ✅ | — | Folder processed mail is moved to, e.g. `Archive` |
| `TODOIST_API_TOKEN` | ✅ | — | Todoist API token |
| `OLLAMA_MODEL` | ✅ | — | Ollama model tag, e.g. `gemma4:e4b` (must be pulled) |
| `IMAP_PORT` | | `993` | IMAP SSL port |
| `OLLAMA_HOST` | | `http://localhost:11434` | Ollama server URL |
| `TODOIST_PROJECT_NAME` | | _(inbox)_ | Target Todoist project by name; omit for your inbox |
| `POLL_INTERVAL` | | `60` | Seconds between mailbox checks |

For the plain-Docker and local paths, copy [.env.example](.env.example) to `.env`
and fill it in. (The compose file carries its config inline — see below.)

## Running with Docker (recommended)

The provided [docker-compose.yml](docker-compose.yml) runs two services — a local
`ollama` and `mail2task` built from the local [Dockerfile](Dockerfile) — and
keeps configuration **inline** in the compose file (edit it directly):

```bash
docker compose up -d --build              # build and start in the background
docker compose exec ollama ollama pull gemma4:e4b   # one-time: pull the model
docker compose logs -f                    # watch it work
docker compose down                       # stop
```

The model is stored in the `ollama_data` volume, so it survives restarts and
only needs pulling once. (These commands work with `podman compose` too.)

To pull a published mail2task image instead of building, set that service's
`image:` to `ghcr.io/OWNER/mail2task:latest` and drop its `build:` line.

## Running locally (without Docker)

Requires Python 3.11+ and a reachable Ollama server.

```bash
pip install .
cp .env.example .env                  # then edit .env
export $(grep -v '^#' .env | xargs)   # load your .env into the shell
mail2task
```

Stop it with `Ctrl-C`; it shuts down cleanly (and handles `SIGTERM`, so
`docker stop` is clean too).

## How a task is built

Every message in `IMAP_FOLDER` is processed each cycle:

1. The Ollama model rewrites the subject into a short, imperative **title** and
   extracts an optional **deadline** (`YYYY-MM-DD`).
2. A Todoist task is created (in `TODOIST_PROJECT_NAME` if set) with its **due
   date set to today**, the extracted **deadline**, and a `mail2task` **label**.
   If a deadline was found the task gets **priority 2**; otherwise it keeps
   Todoist's default priority.
3. The sender and a truncated body preview are added as a **comment**; any
   attachments are uploaded as comments too.
4. The message is marked read and **moved to `IMAP_ARCHIVE_FOLDER`**.

If the Ollama call fails for a message, mail2task falls back to using the raw
subject as the title (no deadline) so no mail is ever dropped.

## Notes

- **All** messages in `IMAP_FOLDER` are processed every cycle and then archived
  to `IMAP_ARCHIVE_FOLDER`, which is why that folder is required — it's what
  stops a message being turned into a task twice.
- The email body is truncated before being sent to Ollama and before being
  stored in the comment.
- Development setup and architecture notes live in [CLAUDE.md](CLAUDE.md).

## License

GPLv3 — see [LICENSE](LICENSE).
