"""LLM client. Swap the body of `generate` for the real model when it exists."""

import os

import httpx

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))


class LLMError(RuntimeError):
    pass


async def generate(
    prompt: str,
) -> str:
    messages = [{"role": "user", "content": prompt}]

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            response = await client.post(
                f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            )
            if response.is_error:
                raise LLMError(f"{response.status_code} from backend: {response.text}")
            data = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(str(exc)) from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected response shape: {data}") from exc
