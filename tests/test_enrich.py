"""Tests for Ollama enrichment and deadline validation in mail2task.enrich."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mail2task.enrich import TaskFields, enrich_with_ollama
from mail2task.mail import Email


def test_deadline_future_kept():
    future = (date.today() + timedelta(days=3)).isoformat()
    assert TaskFields(title="t", deadline=future).deadline == future


def test_deadline_today_kept():
    today = date.today().isoformat()
    assert TaskFields(title="t", deadline=today).deadline == today


def test_deadline_past_dropped():
    past = (date.today() - timedelta(days=1)).isoformat()
    assert TaskFields(title="t", deadline=past).deadline is None


def test_deadline_malformed_dropped():
    assert TaskFields(title="t", deadline="not-a-date").deadline is None


def test_deadline_none_stays_none():
    assert TaskFields(title="t", deadline=None).deadline is None


def test_title_required():
    with pytest.raises(ValidationError):
        TaskFields(deadline=None)  # type: ignore[call-arg]


class _FakeClient:
    def __init__(self, content=None, raise_exc=False):
        self._content = content
        self._raise = raise_exc

    def chat(self, **kwargs):
        if self._raise:
            raise RuntimeError("ollama down")
        return SimpleNamespace(message=SimpleNamespace(content=self._content))


def _email():
    return Email(subject="Subject line", sender="a@example.com", body="body")


def test_enrich_returns_model_fields():
    future = (date.today() + timedelta(days=2)).isoformat()
    client = _FakeClient(json.dumps({"title": "Do thing", "deadline": future}))
    fields = enrich_with_ollama(client, "m", _email())
    assert fields.title == "Do thing"
    assert fields.deadline == future


def test_enrich_falls_back_to_subject_on_error():
    client = _FakeClient(raise_exc=True)
    fields = enrich_with_ollama(client, "m", _email())
    assert fields.title == "Subject line"
    assert fields.deadline is None


def test_enrich_fallback_handles_empty_subject():
    client = _FakeClient(raise_exc=True)
    fields = enrich_with_ollama(client, "m", Email(subject="", sender="a", body=""))
    assert fields.title == "(no subject)"
