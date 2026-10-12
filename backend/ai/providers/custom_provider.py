"""
backend/ai/providers/custom_provider.py
---------------------------------------
Custom OpenAI-compatible AI provider implementation.
Connects to self-hosted LLM endpoints (e.g., Ollama, vLLM, LMStudio, LocalAI).
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


class CustomProvider(AIProvider):
    """Wraps custom OpenAI-compatible endpoint."""

    @property
    def name(self) -> str:
        return "custom"

    def _get_base_url(self) -> str:
        try:
            from auth import current_user_custom_ai_base_url
            user_url = current_user_custom_ai_base_url.get()
            if user_url and user_url.strip():
                url = user_url.strip()
            else:
                url = (os.environ.get("CUSTOM_AI_BASE_URL") or "http://localhost:11434/v1").strip()
        except Exception:
            url = (os.environ.get("CUSTOM_AI_BASE_URL") or "http://localhost:11434/v1").strip()

        # Normalize URL to /chat/completions
        url = url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        return url

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_custom_ai_key
            user_key = current_user_custom_ai_key.get()
            if user_key and user_key.strip():
                return user_key.strip()
        except Exception:
            pass

        return (os.environ.get("CUSTOM_AI_API_KEY") or "").strip()

    def _get_model(self, fallback_model: str) -> str:
        try:
            from auth import current_user_custom_ai_model
            user_model = current_user_custom_ai_model.get()
            if user_model and user_model.strip():
                return user_model.strip()
        except Exception:
            pass

        env_model = (os.environ.get("CUSTOM_AI_MODEL") or "").strip()
        return env_model or fallback_model

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        url = self._get_base_url()
        active_model = self._get_model(model)
        headers = self._get_headers()
        payload: dict = {
            "model": active_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Custom endpoint timed out on {active_model}: {exc}", provider="custom") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"Custom endpoint connection failed ({url}): {exc}", provider="custom") from exc

        if resp.status_code == 429:
            raise ProviderRateLimited(f"Custom endpoint rate limited (429) on {active_model}.", provider="custom", status_code=429)
        elif resp.status_code in (404, 500, 502, 503, 504):
            raise ProviderUnavailable(f"Custom endpoint error ({resp.status_code}) on {active_model}: {resp.text}", provider="custom", status_code=resp.status_code)
        elif resp.status_code >= 400:
            raise ProviderInvalidResponse(f"Custom endpoint rejected ({resp.status_code}): {resp.text}", provider="custom", status_code=resp.status_code)

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderInvalidResponse(f"Custom endpoint invalid JSON response on {active_model}: {exc}", provider="custom") from exc

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        url = self._get_base_url()
        active_model = self._get_model(model)
        headers = self._get_headers()
        payload = {
            "model": active_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            client = httpx.AsyncClient(timeout=120.0)
            async with client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code == 429:
                        raise ProviderRateLimited(f"Custom streaming rate limited (429) on {active_model}.", provider="custom", status_code=429)
                    elif resp.status_code in (404, 500, 502, 503, 504):
                        raise ProviderUnavailable(f"Custom streaming unavailable ({resp.status_code}) on {active_model}.", provider="custom", status_code=resp.status_code)
                    elif resp.status_code >= 400:
                        raise ProviderInvalidResponse(f"Custom stream rejected ({resp.status_code}) on {active_model}.", provider="custom", status_code=resp.status_code)

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
            raise ProviderTimeout(f"Custom endpoint stream timed out on {active_model}: {exc}", provider="custom") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"Custom endpoint streaming connection error on {active_model}: {exc}", provider="custom") from exc

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
        raise ProviderUnavailable("Custom endpoint speech transcription not supported; routed via Groq Whisper.", provider="custom")

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        raise ProviderUnavailable("Custom endpoint TTS not supported; routed via browser TTS or Groq.", provider="custom")
