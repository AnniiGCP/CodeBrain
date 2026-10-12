"""
backend/ai/providers/anthropic_provider.py
-----------------------------------------
Anthropic-compatible AI provider implementation.
Supports:
  - Base URL (default: https://api.anthropic.com/v1)
  - Custom API key
  - Custom models (e.g., claude-3-5-sonnet-20241022, claude-3-haiku-20240307)
  - Required headers (x-api-key, anthropic-version: 2023-06-01)
  - Synchronous chat, streaming chat, vision, and connection diagnostics.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import AsyncGenerator, Optional

import httpx

from ai.exceptions import AIAuthenticationError, AIModelNotFoundError, AIProviderError, AIRateLimitError
from ai.providers.base import AIProvider

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    """
    Anthropic Messages API Provider.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        anthropic_version: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_URL)).rstrip("/")
        self._version = anthropic_version or os.environ.get("ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION)
        self._default_model = model or "claude-3-5-sonnet-20241022"

    @property
    def model(self) -> str:
        return self._default_model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def name(self) -> str:
        return "anthropic"

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_anthropic_key
            user_k = current_user_anthropic_key.get()
            if user_k and user_k.strip():
                return user_k.strip()
        except Exception:
            pass
        return self._api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()

    def _get_base_url(self) -> str:
        return self._base_url

    def _get_headers(self) -> dict[str, str]:
        key = self._get_api_key()
        if not key:
            raise AIAuthenticationError("Anthropic API key is not configured.", provider="anthropic")
        return {
            "x-api-key": key,
            "anthropic-version": self._version,
            "content-type": "application/json",
        }


    def _convert_messages(self, messages: list[dict]) -> tuple[Optional[str], list[dict]]:
        """Converts OpenAI-style messages to Anthropic format (extracts system prompt)."""
        system_prompt: Optional[str] = None
        anthropic_msgs: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            else:
                anthropic_msgs.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": content,
                })

        if not anthropic_msgs:
            anthropic_msgs.append({"role": "user", "content": "Hello"})

        return system_prompt, anthropic_msgs

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        """Synchronous chat completion via Anthropic Messages API."""
        headers = self._get_headers()
        system_prompt, formatted_msgs = self._convert_messages(messages)

        payload: dict = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        url = f"{self._base_url}/messages"
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 401:
                    raise AIAuthenticationError("Invalid Anthropic API key.", provider="anthropic")
                elif resp.status_code == 404:
                    raise AIModelNotFoundError(f"Anthropic model '{model}' not found.", provider="anthropic")
                elif resp.status_code == 429:
                    raise AIRateLimitError("Anthropic rate limit exceeded.", provider="anthropic")
                elif resp.status_code >= 400:
                    raise AIProviderError(f"Anthropic error {resp.status_code}: {resp.text}", provider="anthropic")

                data = resp.json()
                content_blocks = data.get("content", [])
                text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
                return "".join(text_parts).strip()
        except httpx.RequestError as exc:
            raise AIProviderError(f"Network error calling Anthropic API: {exc}", provider="anthropic")

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Asynchronous streaming chat completion."""
        headers = self._get_headers()
        system_prompt, formatted_msgs = self._convert_messages(messages)

        payload: dict = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt

        url = f"{self._base_url}/messages"
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code == 401:
                    raise AIAuthenticationError("Invalid Anthropic API key.", provider="anthropic")
                elif resp.status_code >= 400:
                    err_body = await resp.aread()
                    raise AIProviderError(f"Anthropic stream error: {err_body.decode()}", provider="anthropic")

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if chunk.get("type") == "content_block_delta":
                                delta = chunk.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                        except Exception:
                            continue

    async def stream_vision(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Streaming vision analysis."""
        async for token in self.stream_chat(messages, model, temperature, max_tokens):
            yield token

    async def transcribe(
        self,
        audio_bytes: bytes,
        model: str,
        filename: str = "audio.webm",
    ) -> str:
        raise NotImplementedError("Anthropic provider does not support audio transcription natively.")

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        raise NotImplementedError("Anthropic provider does not support text-to-speech natively.")

    def test_connection(self, model: str = "claude-3-haiku-20240307") -> dict:
        """Runs a diagnostic ping and measures latency."""
        t0 = time.time()
        try:
            res = self.chat(
                [{"role": "user", "content": "ping"}],
                model=model,
                max_tokens=10,
            )
            lat = round((time.time() - t0) * 1000, 1)
            return {"status": "ok", "latency_ms": lat, "response": res, "provider": "anthropic"}
        except Exception as exc:
            return {"status": "error", "error": str(exc), "provider": "anthropic"}
