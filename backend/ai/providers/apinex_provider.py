"""
backend/ai/providers/apinex_provider.py
---------------------------------------
APInex AI Provider implementation for GPT-6 Luna.
Endpoint: https://api.apinex.bond/v1/chat/completions

Key Features:
  - OpenAI-compatible chat completions interface.
  - Streaming and non-streaming responses.
  - Persistent daily quota tracking against 315,000-token budget.
  - Graceful error mapping (401 auth, 429 rate limit / quota, 5xx server errors, timeouts).
  - Cancellation-safe stream handling (releases reservations, avoids ghost writing).
  - Conservative usage estimation when provider omits usage metadata.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator, Optional

import httpx

from ai.exceptions import (
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.providers.base import AIProvider
from ai.quota_manager import (
    check_quota,
    record_usage,
    reserve_quota,
    release_reservation,
)

logger = logging.getLogger("ai.providers.apinex")


class ApinexProvider(AIProvider):
    """Wraps APInex OpenAI-compatible API endpoints for GPT-6 Luna."""

    @property
    def name(self) -> str:
        return "apinex"

    def get_base_url(self) -> str:
        url = os.environ.get("APINEX_BASE_URL", "https://api.apinex.bond/v1").strip().rstrip("/")
        return url or "https://api.apinex.bond/v1"

    def get_model_id(self) -> str:
        return os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna").strip() or "free/gpt-6-luna"

    def is_enabled(self) -> bool:
        enabled_str = os.environ.get("APINEX_ENABLED", "true").lower().strip()
        return enabled_str in ("true", "1", "yes")

    def _get_api_key(self) -> str:
        key = os.environ.get("APINEX_API_KEY", "").strip()
        if not key or key.startswith("your_"):
            raise ProviderUnavailable(
                "APINEX_API_KEY is not configured in the environment.",
                provider="apinex",
            )
        return key

    def is_configured(self) -> bool:
        """Returns True if APInex is enabled and configured with an API key."""
        if not self.is_enabled():
            return False
        key = os.environ.get("APINEX_API_KEY", "").strip()
        return bool(key) and not key.startswith("your_")

    def _estimate_tokens(self, messages: list[dict], completion_text: str = "") -> tuple[int, int, int]:
        """Calculates a documented, conservative token estimate (~4 chars per token)."""
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        prompt_tokens = max(1, prompt_chars // 4)
        comp_tokens = max(0, len(completion_text) // 4)
        total_tokens = prompt_tokens + comp_tokens
        return prompt_tokens, comp_tokens, total_tokens

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        api_key = self._get_api_key()
        req_id = str(uuid.uuid4())[:8]

        # 1. Enforce local daily budget before sending upstream request
        can_proceed, reason, _ = check_quota(estimated_tokens=500)
        if not can_proceed:
            logger.warning("[APINEX] Request blocked: %s", reason)
            raise ProviderRateLimited(
                "APInex daily token limit exhausted. Automatic fallback initiated.",
                provider="apinex",
                status_code=429,
            )

        endpoint = f"{self.get_base_url()}/chat/completions"
        target_model = model or self.get_model_id()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CodeBrain-AI/1.0",
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"APInex request timed out on {target_model}: {exc}", provider="apinex") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"APInex connection failed on {target_model}: {exc}", provider="apinex") from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise ProviderUnavailable(
                f"APInex authentication failure ({resp.status_code}): Invalid or expired API key.",
                provider="apinex",
                status_code=resp.status_code,
            )
        elif resp.status_code == 404:
            raise ProviderUnavailable(
                f"APInex model not found ({resp.status_code}) for '{target_model}'.",
                provider="apinex",
                status_code=404,
            )
        elif resp.status_code == 429:
            raise ProviderRateLimited(
                f"APInex provider-side rate limit or quota exceeded ({resp.status_code}).",
                provider="apinex",
                status_code=429,
            )
        elif resp.status_code in (500, 502, 503, 504):
            raise ProviderUnavailable(
                f"APInex server error ({resp.status_code}).",
                provider="apinex",
                status_code=resp.status_code,
            )
        elif resp.status_code >= 400:
            raise ProviderInvalidResponse(
                f"APInex request rejected ({resp.status_code}): {resp.text}",
                provider="apinex",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderInvalidResponse(f"APInex invalid JSON response on {target_model}: {exc}", provider="apinex") from exc

        # 2. Extract and record token usage
        usage = data.get("usage")
        if usage and isinstance(usage, dict) and "total_tokens" in usage:
            p_tok = usage.get("prompt_tokens", 0)
            c_tok = usage.get("completion_tokens", 0)
            t_tok = usage.get("total_tokens", p_tok + c_tok)
            record_usage(
                total_tokens=t_tok,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                is_estimated=False,
                request_id=req_id,
            )
        else:
            p_est, c_est, t_est = self._estimate_tokens(messages, content)
            record_usage(
                total_tokens=t_est,
                prompt_tokens=p_est,
                completion_tokens=c_est,
                is_estimated=True,
                request_id=req_id,
            )

        return content

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        api_key = self._get_api_key()
        req_id = str(uuid.uuid4())[:8]
        estimated_res = 500

        # 1. Quota check & in-flight reservation
        can_proceed, reason, _ = check_quota(estimated_tokens=estimated_res)
        if not can_proceed:
            logger.warning("[APINEX] Streaming request blocked: %s", reason)
            raise ProviderRateLimited(
                "APInex daily token limit exhausted. Automatic fallback initiated.",
                provider="apinex",
                status_code=429,
            )

        reserved_ok = reserve_quota(estimated_tokens=estimated_res)
        if not reserved_ok:
            raise ProviderRateLimited(
                "APInex in-flight token budget limit reached.",
                provider="apinex",
                status_code=429,
            )

        endpoint = f"{self.get_base_url()}/chat/completions"
        target_model = model or self.get_model_id()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CodeBrain-AI/1.0",
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        generated_chunks: list[str] = []
        captured_usage: Optional[dict] = None

        try:
            client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
            async with client:
                async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                    if resp.status_code == 401 or resp.status_code == 403:
                        raise ProviderUnavailable(
                            f"APInex streaming authentication failure ({resp.status_code}).",
                            provider="apinex",
                            status_code=resp.status_code,
                        )
                    elif resp.status_code == 404:
                        raise ProviderUnavailable(
                            f"APInex model not found ({resp.status_code}) on streaming.",
                            provider="apinex",
                            status_code=404,
                        )
                    elif resp.status_code == 429:
                        raise ProviderRateLimited(
                            f"APInex streaming rate limit or quota exceeded ({resp.status_code}).",
                            provider="apinex",
                            status_code=429,
                        )
                    elif resp.status_code in (500, 502, 503, 504):
                        raise ProviderUnavailable(
                            f"APInex streaming server error ({resp.status_code}).",
                            provider="apinex",
                            status_code=resp.status_code,
                        )
                    elif resp.status_code >= 400:
                        raise ProviderInvalidResponse(
                            f"APInex streaming request rejected ({resp.status_code}).",
                            provider="apinex",
                            status_code=resp.status_code,
                        )

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            obj = json.loads(data_str)
                            # Check if streaming usage metadata is emitted
                            if "usage" in obj and obj["usage"]:
                                captured_usage = obj["usage"]

                            choices = obj.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    generated_chunks.append(token)
                                    yield token
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except (ProviderRateLimited, ProviderUnavailable, ProviderInvalidResponse):
            raise
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"APInex stream timed out on {target_model}: {exc}", provider="apinex") from exc
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("[APINEX] Stream cancelled by client on %s", target_model)
            raise
        except Exception as exc:
            raise ProviderUnavailable(f"APInex stream connection error on {target_model}: {exc}", provider="apinex") from exc
        finally:
            # Reconcile in-flight reservation and persist usage record
            release_reservation(estimated_tokens=estimated_res)
            full_text = "".join(generated_chunks)

            if captured_usage and "total_tokens" in captured_usage:
                p_tok = captured_usage.get("prompt_tokens", 0)
                c_tok = captured_usage.get("completion_tokens", 0)
                t_tok = captured_usage.get("total_tokens", p_tok + c_tok)
                record_usage(
                    total_tokens=t_tok,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    is_estimated=False,
                    request_id=req_id,
                )
            elif full_text or messages:
                p_est, c_est, t_est = self._estimate_tokens(messages, full_text)
                record_usage(
                    total_tokens=t_est,
                    prompt_tokens=p_est,
                    completion_tokens=c_est,
                    is_estimated=True,
                    request_id=req_id,
                )

    async def stream_vision(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        # GPT-6 Luna is configured for chat, reasoning, coding. Vision falls back to verified vision models.
        raise ProviderUnavailable("APInex GPT-6 Luna does not currently support image input.", provider="apinex")

    async def transcribe(
        self,
        audio_bytes: bytes,
        model: str,
        filename: str = "audio.webm",
    ) -> str:
        raise ProviderUnavailable("APInex does not support speech transcription.", provider="apinex")

    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        raise ProviderUnavailable("APInex does not support text-to-speech.", provider="apinex")
