"""
backend/ai/providers/nvidia_provider.py
---------------------------------------
NVIDIA NIM provider implementation for chat, reasoning, streaming, and vision.
Endpoint: https://integrate.api.nvidia.com/v1/chat/completions
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

_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


class NvidiaProvider(AIProvider):
    """Wraps NVIDIA NIM endpoints."""

    @property
    def name(self) -> str:
        return "nvidia"

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_nvidia_key
            user_key = current_user_nvidia_key.get()
            if user_key and user_key.strip():
                return user_key.strip()
        except Exception:
            pass

        key = (
            os.environ.get("NVIDIA_NIM_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("NVCF_API_KEY")
            or ""
        ).strip()
        if not key or key.startswith("your_"):
            from dotenv import load_dotenv
            load_dotenv()
            key = (
                os.environ.get("NVIDIA_NIM_API_KEY")
                or os.environ.get("NVIDIA_API_KEY")
                or os.environ.get("NVCF_API_KEY")
                or ""
            ).strip()
        if not key or key.startswith("your_"):
            raise ProviderUnavailable("NVIDIA_NIM_API_KEY is not configured.", provider="nvidia")
        return key

    def _resolve_model(self, model: str) -> str:
        from ai.registry import NVIDIA_UPSTREAM_MAP
        return NVIDIA_UPSTREAM_MAP.get(model, model)

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        resolved_model = self._resolve_model(model)
        logger.info("[NVIDIA] routing model=%s (resolved upstream=%s)", model, resolved_model)
        payload = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = httpx.post(_NVIDIA_URL, headers=headers, json=payload, timeout=60.0)
            if resp.status_code == 404 and resolved_model != model:
                # Try direct model ID fallback if catalog path 404s
                payload["model"] = model
                resp = httpx.post(_NVIDIA_URL, headers=headers, json=payload, timeout=60.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"NVIDIA request timed out on {model}: {exc}", provider="nvidia") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"NVIDIA connection failed on {model}: {exc}", provider="nvidia") from exc

        if resp.status_code == 429:
            raise ProviderRateLimited(f"NVIDIA rate limit exceeded (429) on {model}.", provider="nvidia", status_code=429)
        elif resp.status_code in (404, 500, 502, 503, 504):
            raise ProviderUnavailable(f"NVIDIA server error ({resp.status_code}) on {model}.", provider="nvidia", status_code=resp.status_code)
        elif resp.status_code >= 400:
            raise ProviderInvalidResponse(f"NVIDIA request rejected ({resp.status_code}): {resp.text}", provider="nvidia", status_code=resp.status_code)

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderInvalidResponse(f"NVIDIA invalid JSON response on {model}: {exc}", provider="nvidia") from exc

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        resolved_model = self._resolve_model(model)
        logger.info("[NVIDIA] stream routing model=%s (resolved upstream=%s)", model, resolved_model)
        payload = {
            "model": resolved_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            client = httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0))
            async with client:
                async with client.stream("POST", _NVIDIA_URL, headers=headers, json=payload) as resp:
                    if resp.status_code == 429:
                        raise ProviderRateLimited(f"NVIDIA streaming rate limited (429) on {model}.", provider="nvidia", status_code=429)
                    elif resp.status_code in (404, 500, 502, 503, 504):
                        raise ProviderUnavailable(f"NVIDIA streaming unavailable ({resp.status_code}) on {model}.", provider="nvidia", status_code=resp.status_code)
                    elif resp.status_code >= 400:
                        raise ProviderInvalidResponse(f"NVIDIA stream rejected ({resp.status_code}) on {model}.", provider="nvidia", status_code=resp.status_code)


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
            raise ProviderTimeout(f"NVIDIA NIM stream timed out on {model}: {exc}", provider="nvidia") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"NVIDIA NIM streaming connection error on {model}: {exc}", provider="nvidia") from exc

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
        # If NVIDIA ASR endpoint is available
        raise ProviderUnavailable("NVIDIA speech transcription fallback not available on this tier.", provider="nvidia")

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        raise ProviderUnavailable("NVIDIA TTS endpoint not available on this tier.", provider="nvidia")
