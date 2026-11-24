"""Tests for the /ask endpoint.

The Claude API is replaced with a fake client, so these tests run offline
and cost nothing.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_response(text="", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.fixture
def fake_claude(monkeypatch):
    """Point main.get_client at a fake and return its messages object."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    messages = FakeMessages(fake_response("FastAPI is a Python web framework."))
    fake = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(main, "get_client", lambda: fake)
    return messages


def test_ask_returns_claudes_answer(fake_claude):
    r = client.post("/ask", json={"question": "What is FastAPI?"})

    assert r.status_code == 200
    assert r.json() == {"answer": "FastAPI is a Python web framework."}
    sent = fake_claude.calls[0]
    assert sent["model"] == main.MODEL
    assert sent["messages"] == [{"role": "user", "content": "What is FastAPI?"}]


def test_ask_refusal_returns_422(fake_claude):
    fake_claude.response = fake_response(stop_reason="refusal")

    r = client.post("/ask", json={"question": "something declined"})

    assert r.status_code == 422
    assert "declined" in r.json()["detail"]


@pytest.mark.parametrize("body", [{"question": ""}, {}])
def test_ask_rejects_empty_or_missing_question(fake_claude, body):
    r = client.post("/ask", json=body)

    assert r.status_code == 422
    assert fake_claude.calls == []


def test_ask_without_api_key_returns_500(fake_claude, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 500
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert fake_claude.calls == []
