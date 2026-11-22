"""Container health reporting: a heartbeat file written by the poll loop and a checker that reads it."""

import os
import sys
import time
from pathlib import Path

HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/mail2task-heartbeat"))

# Extra time allowed on top of the poll interval, so a slow cycle with many emails is not reported as unhealthy.
_GRACE_SECONDS = 600
_MISSED_CYCLES = 3


def beat() -> None:
    """Record that the service just completed a healthy step."""
    try:
        HEARTBEAT_FILE.touch()
    except OSError:
        # Health reporting must never take the service down.
        pass


def is_healthy(now: float | None = None) -> bool:
    """Report whether the last heartbeat is recent enough relative to the poll interval."""
    interval = int(os.environ.get("POLL_INTERVAL") or 60)
    max_age = _MISSED_CYCLES * interval + _GRACE_SECONDS
    try:
        age = (now if now is not None else time.time()) - HEARTBEAT_FILE.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


def main() -> None:
    """Exit with status 0 when healthy and 1 otherwise, for use as a Docker healthcheck."""
    sys.exit(0 if is_healthy() else 1)


if __name__ == "__main__":
    main()
