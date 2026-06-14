"""mail2task — poll an IMAP folder, enrich each email with Ollama, create Todoist tasks."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mail2task")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0+unknown"
