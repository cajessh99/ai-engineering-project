"""Tests for the /ask endpoint.

The Claude API is replaced with a fake client, so these tests run offline
and cost nothing.
"""

from types import SimpleNamespace

import anthropic
import httpx2
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
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def fake_response(text="", stop_reason="end_turn", content=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content if content is not None else [text_block(text)],
    )


API_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


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


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "   \n\t "},
        {"question": "x" * (main.MAX_QUESTION_CHARS + 1)},
        {},
    ],
    ids=["empty", "whitespace", "too-long", "missing"],
)
def test_ask_rejects_invalid_question(fake_claude, body):
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


def test_ask_strips_surrounding_whitespace(fake_claude):
    client.post("/ask", json={"question": "  What is FastAPI?\n"})

    assert fake_claude.calls[0]["messages"][0]["content"] == "What is FastAPI?"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
def test_ask_cut_off_answer_returns_502(fake_claude, stop_reason):
    fake_claude.response = fake_response("A partial ans", stop_reason=stop_reason)

    r = client.post("/ask", json={"question": "Write a long guide"})

    assert r.status_code == 502
    assert "cut off" in r.json()["detail"]


def test_ask_empty_answer_returns_502(fake_claude):
    fake_claude.response = fake_response(content=[])

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 502
    assert "no text" in r.json()["detail"]


def test_ask_after_fallback_returns_only_fallback_models_text(fake_claude):
    fake_claude.response = fake_response(
        content=[
            text_block("Partial text from the first model"),
            SimpleNamespace(type="fallback"),
            text_block("The fallback "),
            text_block("model's answer."),
        ]
    )

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 200
    assert r.json() == {"answer": "The fallback model's answer."}


def test_ask_api_error_returns_502_without_leaking_details(fake_claude):
    fake_claude.response = anthropic.InternalServerError(
        "secret internal detail",
        response=httpx2.Response(500, request=API_REQUEST),
        body=None,
    )

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 502
    assert "500" in r.json()["detail"]
    assert "secret internal detail" not in r.json()["detail"]


def test_ask_connection_error_returns_502(fake_claude):
    fake_claude.response = anthropic.APIConnectionError(request=API_REQUEST)

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 502
    assert "Could not reach" in r.json()["detail"]


def test_ask_rate_limit_returns_429(fake_claude):
    fake_claude.response = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=API_REQUEST), body=None
    )

    r = client.post("/ask", json={"question": "hi"})

    assert r.status_code == 429


def test_client_has_short_timeout(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    main.get_client.cache_clear()
    try:
        assert main.get_client().timeout == main.REQUEST_TIMEOUT_SECONDS
    finally:
        main.get_client.cache_clear()
