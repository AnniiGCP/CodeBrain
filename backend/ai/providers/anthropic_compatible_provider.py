"""
backend/ai/providers/anthropic_compatible_provider.py
-----------------------------------------------------
Generic Anthropic-Compatible provider implementation.
Allows configuring:
  - Base URL (user provided custom endpoint)
  - API Key
  - Model ID
Implements the Anthropic Messages API format.
"""
from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator, Optional

import httpx

from ai.exceptions import AIAuthenticationError, AIModelNotFoundError, AIProviderError, AIRateLimitError
from ai.providers.base import AIProvider

logger = logging.getLogger(__name__)


class AnthropicCompatibleProvider(AIProvider):
    """Wraps generic Anthropic-compatible endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._default_base_url = (base_url or os.environ.get("ANTHROPIC_COMPATIBLE_BASE_URL", "")).rstrip("/")
        self._default_api_key = api_key or os.environ.get("ANTHROPIC_COMPATIBLE_API_KEY", "")
        self._default_model = model or os.environ.get("ANTHROPIC_COMPATIBLE_MODEL", "claude-compatible")
        self._version = "2023-06-01"

    @property
    def name(self) -> str:
        return "anthropic-compatible"

    @property
    def is_available(self) -> bool:
        return bool(self._get_api_key())

    def _get_base_url(self) -> str:
        try:
            from auth import current_user_anthropic_compatible_base_url
            u = current_user_anthropic_compatible_base_url.get()
            if u and u.strip():
                return u.strip().rstrip("/")
        except Exception:
            pass
        return self._default_base_url or "https://api.anthropic.com/v1"

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_anthropic_compatible_key
            k = current_user_anthropic_compatible_key.get()
            if k and k.strip():
                return k.strip()
        except Exception:
            pass
        return self._default_api_key

    def _get_model(self, fallback: str) -> str:
        try:
            from auth import current_user_anthropic_compatible_model
            m = current_user_anthropic_compatible_model.get()
            if m and m.strip():
                return m.strip()
        except Exception:
            pass
        return fallback or self._default_model

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "anthropic-version": self._version,
            "content-type": "application/json",
        }
        key = self._get_api_key()
        if key:
            headers["x-api-key"] = key
        return headers

    def _convert_messages(self, messages: list[dict]) -> tuple[Optional[str], list[dict]]:
        system_prompt: Optional[str] = None
        formatted: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            else:
                formatted.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": content,
                })
        if not formatted:
            formatted.append({"role": "user", "content": "Hello"})
        return system_prompt, formatted

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        base_url = self._get_base_url()
        active_model = self._get_model(model)
        headers = self._get_headers()
        system_prompt, formatted_msgs = self._convert_messages(messages)

        payload: dict = {
            "model": active_model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        url = f"{base_url}/messages" if not base_url.endswith("/messages") else base_url
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 401:
                    raise AIAuthenticationError("Invalid API key for Anthropic-Compatible endpoint.", provider="anthropic-compatible")
                elif resp.status_code == 404:
                    raise AIModelNotFoundError(f"Model '{active_model}' not found on endpoint.", provider="anthropic-compatible")
                elif resp.status_code == 429:
                    raise AIRateLimitError("Rate limit exceeded on Anthropic-Compatible endpoint.", provider="anthropic-compatible")
                elif resp.status_code >= 400:
                    raise AIProviderError(f"Anthropic-Compatible error {resp.status_code}: {resp.text}", provider="anthropic-compatible")

                data = resp.json()
                content_blocks = data.get("content", [])
                text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
                return "".join(text_parts).strip()
        except httpx.RequestError as exc:
            raise AIProviderError(f"Network error calling Anthropic-Compatible endpoint: {exc}", provider="anthropic-compatible")

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        base_url = self._get_base_url()
        active_model = self._get_model(model)
        headers = self._get_headers()
        system_prompt, formatted_msgs = self._convert_messages(messages)

        payload: dict = {
            "model": active_model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt

        url = f"{base_url}/messages" if not base_url.endswith("/messages") else base_url
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code == 401:
                    raise AIAuthenticationError("Invalid API key for Anthropic-Compatible endpoint.", provider="anthropic-compatible")
                elif resp.status_code >= 400:
                    err_body = await resp.aread()
                    raise AIProviderError(f"Anthropic-Compatible stream error: {err_body.decode()}", provider="anthropic-compatible")

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
        async for token in self.stream_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens):
            yield token

    async def transcribe(self, audio_bytes: bytes, model: str, filename: str = "audio.webm") -> str:
        raise AIProviderError("Speech transcription not supported by Anthropic-Compatible provider.", provider="anthropic-compatible")

    async def tts(self, text: str, model: str) -> bytes:
        raise AIProviderError("TTS not supported by Anthropic-Compatible provider.", provider="anthropic-compatible")
