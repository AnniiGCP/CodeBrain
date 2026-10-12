"""
backend/ai/providers/openrouter_provider.py
-------------------------------------------
OpenRouter AI provider implementation for unified access to multiple LLM models.
Endpoint: https://openrouter.ai/api/v1/chat/completions
"""
from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator

import httpx

from ai.exceptions import (
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.providers.base import AIProvider

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(AIProvider):
    """Wraps OpenRouter OpenAI-compatible chat and vision endpoints."""

    @property
    def name(self) -> str:
        return "openrouter"

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_openrouter_key
            user_key = current_user_openrouter_key.get()
            if user_key and user_key.strip():
                return user_key.strip()
        except Exception:
            pass

        key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not key:
            from dotenv import load_dotenv
            load_dotenv()
            key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not key or key.startswith("your_"):
            raise ProviderUnavailable("OPENROUTER_API_KEY is not configured.", provider="openrouter")
        return key

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://codebrain.dev",
            "X-Title": "CodeBrain AI System",
        }

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        headers = self._get_headers()
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = httpx.post(_OPENROUTER_URL, headers=headers, json=payload, timeout=60.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"OpenRouter request timed out on {model}: {exc}", provider="openrouter") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"OpenRouter connection failed on {model}: {exc}", provider="openrouter") from exc

        if resp.status_code == 429:
            raise ProviderRateLimited(f"OpenRouter rate limit exceeded (429) on {model}.", provider="openrouter", status_code=429)
        elif resp.status_code in (404, 500, 502, 503, 504):
            raise ProviderUnavailable(f"OpenRouter server error ({resp.status_code}) on {model}.", provider="openrouter", status_code=resp.status_code)
        elif resp.status_code >= 400:
            raise ProviderInvalidResponse(f"OpenRouter request rejected ({resp.status_code}): {resp.text}", provider="openrouter", status_code=resp.status_code)

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderInvalidResponse(f"OpenRouter invalid JSON response on {model}: {exc}", provider="openrouter") from exc

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        headers = self._get_headers()
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            client = httpx.AsyncClient(timeout=120.0)
            async with client:
                async with client.stream("POST", _OPENROUTER_URL, headers=headers, json=payload) as resp:
                    if resp.status_code == 429:
                        raise ProviderRateLimited(f"OpenRouter streaming rate limited (429) on {model}.", provider="openrouter", status_code=429)
                    elif resp.status_code in (404, 500, 502, 503, 504):
                        raise ProviderUnavailable(f"OpenRouter streaming unavailable ({resp.status_code}) on {model}.", provider="openrouter", status_code=resp.status_code)
                    elif resp.status_code >= 400:
                        raise ProviderInvalidResponse(f"OpenRouter stream rejected ({resp.status_code}) on {model}.", provider="openrouter", status_code=resp.status_code)

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            obj = json.loads(data_str)
                            delta = obj["choices"][0]["delta"]
                            token = delta.get("content", "")
                            if token:
                                yield token
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except (ProviderRateLimited, ProviderUnavailable, ProviderInvalidResponse):
            raise
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"OpenRouter stream timed out on {model}: {exc}", provider="openrouter") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"OpenRouter streaming connection error on {model}: {exc}", provider="openrouter") from exc

    async def stream_vision(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        async for token in self.stream_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens):
            yield token

    async def transcribe(
        self,
        audio_bytes: bytes,
        model: str,
        filename: str = "audio.webm",
    ) -> str:
        raise ProviderUnavailable("OpenRouter speech transcription not supported; routed via Groq Whisper.", provider="openrouter")

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        raise ProviderUnavailable("OpenRouter TTS not supported; routed via browser TTS or Groq.", provider="openrouter")
