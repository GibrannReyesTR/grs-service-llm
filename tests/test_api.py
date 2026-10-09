"""API tests. The LLM backend is always mocked; no Ollama needed."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import llm
import main

client = TestClient(main.app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": llm.LLM_MODEL}


def test_generate_ok(monkeypatch):
    async def fake_generate(prompt: str) -> str:
        return f"echo: {prompt}"

    monkeypatch.setattr(main, "generate", fake_generate)

    response = client.post("/generate", json={"prompt": "hi"})
    assert response.status_code == 200
    assert response.json() == {"model": llm.LLM_MODEL, "output": "echo: hi"}


def test_generate_backend_error_returns_502(monkeypatch):
    async def failing_generate(prompt: str) -> str:
        raise llm.LLMError("boom")

    monkeypatch.setattr(main, "generate", failing_generate)

    response = client.post("/generate", json={"prompt": "hi"})
    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"prompt": ""}, {"prompt": "x" * 20_001}])
def test_generate_rejects_invalid_prompt(body):
    assert client.post("/generate", json=body).status_code == 422


def _mock_backend(monkeypatch, handler):
    """Make llm.generate talk to an in-memory fake backend instead of the network."""
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw)
    )


def test_llm_sends_chat_messages_and_returns_content(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    _mock_backend(monkeypatch, handler)

    assert asyncio.run(llm.generate("hi")) == "hello"
    assert seen["url"].endswith("/chat/completions")
    assert b'"messages"' in seen["json"]


def test_llm_error_includes_backend_body(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model 'x' not found"}})

    _mock_backend(monkeypatch, handler)

    with pytest.raises(llm.LLMError, match="not found"):
        asyncio.run(llm.generate("hi"))


def test_llm_unexpected_response_shape(monkeypatch):
    _mock_backend(monkeypatch, lambda request: httpx.Response(200, json={"nope": 1}))

    with pytest.raises(llm.LLMError, match="unexpected response shape"):
        asyncio.run(llm.generate("hi"))
