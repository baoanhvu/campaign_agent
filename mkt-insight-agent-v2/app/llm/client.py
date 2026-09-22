"""OpenAI-compatible LLM client with retry/backoff/rate-limit.

Works with GreenNode MaaS (OpenAI-compatible endpoint).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.settings import get_settings
from app.llm.rate_limiter import TokenBucket
from app.errors import LLMError, LLMUnavailableError
from app.logging_ import get_logger

_log = get_logger("llm.client")


class LLMClient:
    def __init__(self, model: str | None = None, judge_model: str | None = None):
        s = get_settings().llm
        self._client = AsyncOpenAI(api_key=s.api_key, base_url=s.base_url, timeout=s.timeout_s)
        self.model = model or s.model
        self.judge_model = judge_model or s.judge_model
        self._bucket = TokenBucket(rate_rpm=s.rate_limit_rpm)
        self._max_retries = s.max_retries

    async def chat(self, messages: list[dict[str, str]], *,
                   temperature: float = 0.0, max_tokens: int = 2048,
                   model: str | None = None) -> str:
        """Non-streaming chat completion."""
        wait = self._bucket.acquire()
        if wait > 0:
            _log.info("Rate limited, waited %.1fs", wait)
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                if attempt < self._max_retries - 1:
                    backoff = 2 ** attempt
                    _log.warning("LLM attempt %d failed: %s, retrying in %ds", attempt + 1, exc, backoff)
                    await asyncio.sleep(backoff)
                else:
                    _log.error("LLM failed after %d attempts: %s", self._max_retries, exc)
                    raise LLMUnavailableError(f"LLM unavailable: {exc}") from exc
        raise LLMError("LLM chat failed")

    async def stream(self, messages: list[dict[str, str]], *,
                     temperature: float = 0.0, max_tokens: int = 2048,
                     model: str | None = None) -> AsyncIterator[str]:
        """Streaming chat completion — yields token strings."""
        wait = self._bucket.acquire()
        if wait > 0:
            _log.info("Rate limited, waited %.1fs", wait)
        try:
            stream = await self._client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            _log.error("LLM stream failed: %s", exc)
            raise LLMUnavailableError(f"LLM stream failed: {exc}") from exc

def get_client() -> LLMClient:
    return LLMClient()
