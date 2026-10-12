"""
backend/ai/providers/groq_provider.py
-------------------------------------
Groq provider implementation for chat, streaming, vision, and transcription.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
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

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(AIProvider):
    """Wraps Groq HTTP REST and SDK endpoints."""

    @property
    def name(self) -> str:
        return "groq"

    def _get_api_key(self) -> str:
        try:
            from auth import current_user_groq_key
            user_key = current_user_groq_key.get()
            if user_key and user_key.strip():
                return user_key.strip()
        except Exception:
            pass

        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise ProviderUnavailable("GROQ_API_KEY is not configured.", provider="groq")
        return key

    def _resolve_model(self, model: str) -> str:
        # Map decommissioned or unavailable Groq model IDs to currently active models
        KNOWN_GROQ_ACTIVE = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "allam-2-7b")
        if model in KNOWN_GROQ_ACTIVE:
            return model
        # If llama-3.3 or llama-3.1 or unknown requested, route to active powerhouse gpt-oss-120b or gpt-oss-20b
        if "fast" in model.lower() or "instant" in model.lower() or "8b" in model.lower():
            return "openai/gpt-oss-20b"
        return "openai/gpt-oss-120b"

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        actual_model = self._resolve_model(model)
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": actual_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = httpx.post(_GROQ_URL, headers=headers, json=payload, timeout=60.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Groq request timed out on {model}: {exc}", provider="groq") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"Groq connection failed on {model}: {exc}", provider="groq") from exc

        if resp.status_code == 429:
            raise ProviderRateLimited(f"Groq rate limit exceeded (429) on {model}.", provider="groq", status_code=429)
        elif resp.status_code in (404, 500, 502, 503, 504):
            raise ProviderUnavailable(f"Groq server error ({resp.status_code}) on {model}.", provider="groq", status_code=resp.status_code)
        elif resp.status_code >= 400:
            raise ProviderInvalidResponse(f"Groq request rejected ({resp.status_code}): {resp.text}", provider="groq", status_code=resp.status_code)

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderInvalidResponse(f"Groq invalid JSON response on {model}: {exc}", provider="groq") from exc

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        actual_model = self._resolve_model(model)
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": actual_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            client = httpx.AsyncClient(timeout=120.0)
            async with client:
                async with client.stream("POST", _GROQ_URL, headers=headers, json=payload) as resp:
                    if resp.status_code == 429:
                        raise ProviderRateLimited(f"Groq streaming rate limited (429) on {model}.", provider="groq", status_code=429)
                    elif resp.status_code in (404, 500, 502, 503, 504):
                        raise ProviderUnavailable(f"Groq streaming unavailable ({resp.status_code}) on {model}.", provider="groq", status_code=resp.status_code)
                    elif resp.status_code >= 400:
                        raise ProviderInvalidResponse(f"Groq stream rejected ({resp.status_code}) on {model}.", provider="groq", status_code=resp.status_code)

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
            raise ProviderTimeout(f"Groq stream timed out on {model}: {exc}", provider="groq") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"Groq streaming connection error on {model}: {exc}", provider="groq") from exc

    async def stream_vision(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        # Uses standard stream_chat with vision payload / model
        async for token in self.stream_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens):
            yield token

    async def transcribe(
        self,
        audio_bytes: bytes,
        model: str,
        filename: str = "audio.webm",
    ) -> str:
        api_key = self._get_api_key()
        from groq import Groq
        client = Groq(api_key=api_key)

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(filename, audio_file),
                    model=model,
                    response_format="text",
                    language="en",
                )
            return transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate limit" in err_str:
                raise ProviderRateLimited(f"Groq Whisper rate limited on {model}: {exc}", provider="groq", status_code=429) from exc
            elif "timeout" in err_str:
                raise ProviderTimeout(f"Groq Whisper timed out on {model}: {exc}", provider="groq") from exc
            raise ProviderUnavailable(f"Groq Whisper transcription failed on {model}: {exc}", provider="groq") from exc
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        # Groq Orpheus / TTS implementation placeholder
        return b""
