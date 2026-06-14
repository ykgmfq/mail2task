# mail2task

Turn incoming email into Todoist tasks.
mail2task polls an IMAP folder and, for each message, asks a local **Ollama** model to write a clean, actionable task title and extract an optional deadline.
Every task lands **due today** so it surfaces for review, carries a `mail2task` label, and includes the original sender and a body preview as a comment.
The processed message is archived immediately so it is never handled twice.
It runs continuously, checking for new mail on a configurable interval.

Setup, configuration, and usage instructions are in the [wiki](../../wiki).

## License

GPLv3 — see [LICENSE](LICENSE).
