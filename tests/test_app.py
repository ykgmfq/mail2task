"""Tests for config loading and the process_mailbox idempotency boundary."""

import contextlib
import threading

import pytest

from mail2task import app
from mail2task.enrich import TaskFields
from mail2task.mail import Email

_REQUIRED = {
    "IMAP_HOST": "h",
    "IMAP_USER": "u",
    "IMAP_PASSWORD": "p",
    "IMAP_FOLDER": "INBOX",
    "IMAP_ARCHIVE_FOLDER": "Archive",
    "TODOIST_API_TOKEN": "t",
    "OLLAMA_MODEL": "m",
}


def _set_env(monkeypatch, **extra):
    for key in set(app.REQUIRED_CONFIG) | set(app.INT_CONFIG):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**_REQUIRED, **extra}.items():
        monkeypatch.setenv(key, value)


def test_load_config_ok(monkeypatch):
    _set_env(monkeypatch)
    cfg = app.load_config()
    assert cfg.imap_host == "h"
    assert cfg.poll_interval == 60  # default applied, parsed to int


def test_load_config_missing_key_exits(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.delenv("IMAP_HOST")
    with pytest.raises(SystemExit):
        app.load_config()


def test_load_config_bad_int_exits(monkeypatch):
    _set_env(monkeypatch, POLL_INTERVAL="soon")
    with pytest.raises(SystemExit):
        app.load_config()


def _ctx():
    """A Context whose only meaningful field is the archive folder and model;
    the clients are faked out via monkeypatch in the tests below."""
    config = app.Config(
        imap_host="h",
        imap_user="u",
        imap_password="p",
        imap_folder="INBOX",
        imap_archive_folder="Archive",
        todoist_api_token="t",
        ollama_model="m",
    )
    return app.Context(config=config, ollama=None, todoist=None, project_id=None)


class _FakeIMAP:
    def __init__(self):
        self.expunged = False

    def expunge(self):
        self.expunged = True


def _patch_pipeline(monkeypatch, imap, calls, archive_raises=False):
    """Wire process_mailbox's collaborators to fakes that record an ordered log."""

    @contextlib.contextmanager
    def fake_connect(cfg):
        yield imap

    def fake_iter_all(_imap):
        yield b"1", Email(subject="s", sender="a@x.com", body="b")

    def fake_enrich(client, model, email):
        return TaskFields(title="t", deadline=None)

    def fake_create_task(todoist, cfg, fields, comment):
        calls.append("create_task")
        return "task-1"

    def fake_mark_seen(_imap, msg_id):
        calls.append("mark_seen")

    def fake_attach(todoist, cfg, task_id, attachments):
        calls.append("attach")

    def fake_archive(_imap, msg_id, folder):
        calls.append("archive")
        if archive_raises:
            raise RuntimeError("archive failed")

    monkeypatch.setattr(app.mail, "connect", fake_connect)
    monkeypatch.setattr(app.mail, "iter_all", fake_iter_all)
    monkeypatch.setattr(app.mail, "mark_seen", fake_mark_seen)
    monkeypatch.setattr(app.mail, "archive_message", fake_archive)
    monkeypatch.setattr(app, "enrich_with_ollama", fake_enrich)
    monkeypatch.setattr(app, "create_task", fake_create_task)
    monkeypatch.setattr(app, "add_attachment_comments", fake_attach)
    monkeypatch.setattr(app, "build_comment", lambda email: "comment")


def test_process_mailbox_marks_seen_after_create_before_archive(monkeypatch):
    calls = []
    imap = _FakeIMAP()
    _patch_pipeline(monkeypatch, imap, calls)

    app.process_mailbox(_ctx())

    assert calls == ["create_task", "mark_seen", "attach", "archive"]
    assert calls.index("mark_seen") < calls.index("archive")
    assert imap.expunged is True


def test_process_mailbox_archive_failure_does_not_recreate_task(monkeypatch):
    calls = []
    imap = _FakeIMAP()
    _patch_pipeline(monkeypatch, imap, calls, archive_raises=True)

    # The archive error is isolated per message and must not abort the cycle.
    app.process_mailbox(_ctx())

    # Task created once, and seen was set before the archive blew up, so the
    # next cycle's UNSEEN search would skip this message — no duplicate.
    assert calls.count("create_task") == 1
    assert calls.index("mark_seen") < calls.index("archive")


def test_poll_loop_stops_when_event_set(monkeypatch):
    stop = threading.Event()
    cycles = []

    def fake_process(ctx):
        cycles.append(ctx)
        stop.set()  # ask the loop to stop after this one cycle

    monkeypatch.setattr(app, "process_mailbox", fake_process)
    app.poll_loop(_ctx(), stop, interval=0)

    assert len(cycles) == 1  # ran exactly one cycle, then observed the stop
