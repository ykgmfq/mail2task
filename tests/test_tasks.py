"""Tests for comment building and Todoist task creation in mail2task.tasks."""

from datetime import date, timedelta
from types import SimpleNamespace

from mail2task.enrich import TaskFields
from mail2task.mail import Email
from mail2task.tasks import build_comment, create_task


def test_build_comment_with_body():
    comment = build_comment(Email(subject="s", sender="Alice <a@x.com>", body="hello"))
    assert "**From:** Alice <a@x.com>" in comment
    assert "hello" in comment
    assert "truncated" not in comment


def test_build_comment_no_body():
    comment = build_comment(Email(subject="s", sender="a@x.com", body=""))
    assert comment == "**From:** a@x.com"


def test_build_comment_truncates_long_body():
    comment = build_comment(Email(subject="s", sender="a", body="x" * 3000))
    assert "*(truncated)*" in comment
    assert comment.count("x") == 2000


class _FakeTodoist:
    def __init__(self):
        self.add_task_kwargs = None
        self.comments = []

    def add_task(self, content, **kwargs):
        self.add_task_kwargs = {"content": content, **kwargs}
        return SimpleNamespace(id="task-1")

    def add_comment(self, content, **kwargs):
        self.comments.append((content, kwargs))


def test_create_task_with_deadline():
    api = _FakeTodoist()
    deadline = (date.today() + timedelta(days=5)).isoformat()
    fields = TaskFields(title="Do it", deadline=deadline)
    task_id = create_task(api, "p1", fields, "a comment")

    assert task_id == "task-1"
    kw = api.add_task_kwargs
    assert kw["content"] == "Do it"
    assert kw["project_id"] == "p1"
    assert kw["priority"] == 2
    assert kw["due_date"] == date.today()
    assert kw["deadline_date"] == date.fromisoformat(deadline)
    assert kw["labels"] == ["mail2task"]
    assert api.comments == [("a comment", {"task_id": "task-1"})]


def test_create_task_without_deadline_uses_defaults():
    api = _FakeTodoist()
    fields = TaskFields(title="No date", deadline=None)
    create_task(api, None, fields, "c")

    kw = api.add_task_kwargs
    assert kw["priority"] is None
    assert kw["deadline_date"] is None
    assert kw["project_id"] is None
    assert kw["due_date"] == date.today()
