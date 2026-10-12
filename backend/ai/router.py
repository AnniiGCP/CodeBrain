"""
backend/ai/router.py
--------------------
Centralized AI Router for Groq and NVIDIA NIM.
Dispatches requests based on task type with automatic fallback, mid-stream interruption protection,
and structured observability logging.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import AsyncGenerator, Literal

from ai.config import (
    TaskType,
    get_routing_table,
    get_model_for_task,
    getModelForTask,
    record_model_error,
    record_model_success,
    get_model_health,
)
from ai.exceptions import (
    AIProviderError,
    AllProvidersFailedError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.providers.base import AIProvider
from ai.providers.groq_provider import GroqProvider
from ai.providers.nvidia_provider import NvidiaProvider
from ai.providers.openrouter_provider import OpenRouterProvider
from ai.providers.custom_provider import CustomProvider
from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.anthropic_compatible_provider import AnthropicCompatibleProvider
from ai.providers.apinex_provider import ApinexProvider
from ai.issue_fix_router import route_issue_fix, clean_and_normalize_diff, IssueFixResult
from pathlib import Path

logger = logging.getLogger("ai.router")
logger.setLevel(logging.INFO)
# Also log to a persistent file for easy auditing
_log_file = Path(__file__).parent.parent / "ai_router.log"
_fh = logging.FileHandler(_log_file, mode="a", encoding="utf-8")
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

# Registry of providers
_PROVIDERS: dict[str, AIProvider] = {
    "nvidia": NvidiaProvider(),
    "groq": GroqProvider(),
    "apinex": ApinexProvider(),
    "openai-compatible": CustomProvider(),
    "custom": CustomProvider(),  # alias
    "anthropic-compatible": AnthropicCompatibleProvider(),
}


def _get_provider(name: str) -> AIProvider:
    provider = _PROVIDERS.get(name.lower().strip())
    if not provider:
        raise AIProviderError(
            f"Unknown AI provider '{name}'. Supported: 'nvidia', 'groq', 'apinex', 'openai-compatible', 'anthropic-compatible'."
        )
    return provider



def _log_event(
    task: str,
    provider: str,
    model: str,
    status: str | int,
    latency_ms: int | None = None,
    is_fallback: bool = False,
    error_cat: str | None = None,
) -> None:
    """Emits structured observability log line."""
    prefix = "[AI] fallback" if is_fallback else f"[AI] task={task}"
    lat_str = f" latency={latency_ms}ms" if latency_ms is not None else ""
    fb_str = " fallback_used=true" if is_fallback else ""
    err_str = f" error_category={error_cat}" if error_cat else ""
    log_line = f"{prefix} provider={provider} model={model} status={status}{lat_str}{fb_str}{err_str}"
    if str(status) in ("success", "200"):
        logger.info(log_line)
    else:
        logger.warning(log_line)


# ── Chat & Reasoning Dispatchers ───────────────────────────────────────────────

def _format_provider_diagnostic(provider: str, model: str, exc: Exception) -> str:
    """Extracts genuine, accurate, human-readable error reasons from provider exceptions."""
    p_name = {
        "groq": "Groq",
        "nvidia": "NVIDIA",
        "apinex": "APInex",
        "openrouter": "OpenRouter",
        "custom": "OpenAI-Compatible",
        "openai-compatible": "OpenAI-Compatible",
        "anthropic": "Anthropic",
        "anthropic-compatible": "Anthropic-Compatible",
    }.get(provider.lower(), provider.upper())
    err_str = str(exc).strip()
    status_code = getattr(exc, "status_code", None)

    # 0. Quota / daily token budget exhaustion
    if "daily token limit" in err_str.lower() or "daily budget" in err_str.lower() or "quota exhausted" in err_str.lower():
        return f"{p_name} Daily Token Budget Exhausted (315,000 tokens reached for today)."

    # 1. Missing / Unconfigured Key
    if "not configured" in err_str.lower() or "not set" in err_str.lower():
        return f"{p_name} API Key is not configured. Please configure it in Settings."

    # 2. Authentication failure (401 / Invalid API Key)
    if status_code == 401 or "401" in err_str or "unauthorized" in err_str.lower() or "invalid api key" in err_str.lower():
        return f"{p_name} Authentication Failed (401 Unauthorized): Invalid or expired API Key."

    # 3. Rate Limit / Quota Exceeded (429)
    if status_code == 429 or "429" in err_str or "rate limit" in err_str.lower():
        return f"{p_name} Rate Limit Exceeded (429): Quota/TPM limit reached. Please retry in a few seconds."

    # 4. Timeout
    if isinstance(exc, ProviderTimeout) or "timeout" in err_str.lower() or "timed out" in err_str.lower():
        return f"{p_name} Request Timed Out on model `{model}`."

    # 5. Upstream server errors (500, 502, 503, 504)
    if status_code and status_code >= 500:
        return f"{p_name} Upstream Service Error ({status_code}): Service is temporarily unavailable."

    # 6. Model not found / 404
    if status_code == 404 or "model_not_found" in err_str.lower():
        return f"{p_name} Model Error (404): Model `{model}` is not accessible or has been updated."

    # Default: Return clean message
    clean_msg = err_str.split("\n")[0][:160]
    return f"{p_name} Error on `{model}`: {clean_msg}"


def _format_all_providers_failed_message(
    primary_prov: str,
    primary_model: str,
    primary_exc: Exception,
    fallback_prov: str | None = None,
    fallback_model: str | None = None,
    fallback_exc: Exception | None = None,
) -> str:
    p_diag = _format_provider_diagnostic(primary_prov, primary_model, primary_exc)
    lines = [
        "⚠️ **AI Service Error Diagnosis:**",
        f"- **Primary ({primary_prov.upper()} • `{primary_model}`)**: {p_diag}",
    ]
    if fallback_prov and fallback_model and fallback_exc:
        fb_diag = _format_provider_diagnostic(fallback_prov, fallback_model, fallback_exc)
        lines.append(f"- **Fallback ({fallback_prov.upper()} • `{fallback_model}`)**: {fb_diag}")
    lines.append("\n*Tip: Configure your NVIDIA, Groq, or Compatible API keys under Settings to restore full AI capabilities.*")

    return "\n".join(lines)


def _execute_chat(
    task_type: TaskType | str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
    response_format: dict | None = None,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    context_size: int = 0,
) -> str:
    """Executes synchronous chat with multi-stage fallback cascading and health tracking."""
    decision = get_model_for_task(
        task=str(task_type),
        context_size=context_size,
        user_preferred_provider=preferred_provider,
        user_preferred_model=preferred_model,
    )
    targets = [
        {"provider": decision["provider"], "model": decision["modelId"], "is_fallback": False}
    ]
    for fb in decision.get("fallbackChain", []):
        targets.append({"provider": fb["provider"], "model": fb["modelId"], "is_fallback": True})

    errors: list[Exception] = []
    first_target = targets[0]

    for idx, target in enumerate(targets):
        prov_name = target["provider"]
        model_name = target["model"]
        is_fb = target["is_fallback"]
        t0 = time.time()
        prov_instance = _get_provider(prov_name)
        max_retries = 1 if not is_fb else 0

        for attempt in range(max_retries + 1):
            try:
                res = prov_instance.chat(
                    messages=messages,
                    model=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                latency = int((time.time() - t0) * 1000)
                record_model_success(prov_name, model_name, latency)
                _log_event(task=str(task_type), provider=prov_name, model=model_name, status="success", latency_ms=latency, is_fallback=is_fb)
                return res
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                record_model_error(prov_name, model_name, exc, status_code)
                if attempt < max_retries and isinstance(exc, (ProviderTimeout, ProviderRateLimited, ProviderUnavailable)):
                    backoff_s = 1.0 * (attempt + 1)
                    logger.info("[AI] Primary %s failed (%s), retrying in %.1fs (attempt %d/%d)...", prov_name, exc, backoff_s, attempt + 1, max_retries)
                    time.sleep(backoff_s)
                    continue
                latency = int((time.time() - t0) * 1000)
                _log_event(
                    task=str(task_type),
                    provider=prov_name,
                    model=model_name,
                    status=status_code or "error",
                    latency_ms=latency,
                    is_fallback=is_fb,
                    error_cat=exc.__class__.__name__,
                )
                errors.append(exc)
                break

    # All targets in chain failed
    last_fb = targets[1] if len(targets) > 1 else None
    last_err = errors[-1] if errors else Exception("Execution failed")
    first_err = errors[0] if errors else last_err
    diag_msg = _format_all_providers_failed_message(
        first_target["provider"], first_target["model"], first_err,
        last_fb["provider"] if last_fb else None, last_fb["model"] if last_fb else None, last_err,
    )
    raise AllProvidersFailedError(message=diag_msg, errors=errors) from last_err


_execute_sync_chat = _execute_chat


async def _execute_stream_chat(
    task_type: TaskType | str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    context_size: int = 0,
) -> AsyncGenerator[str, None]:
    """
    Executes streaming chat with pre-stream fallback cascading and mid-stream interruption protection.
    """
    decision = get_model_for_task(
        task=str(task_type),
        context_size=context_size,
        user_preferred_provider=preferred_provider,
        user_preferred_model=preferred_model,
    )
    targets = [
        {"provider": decision["provider"], "model": decision["modelId"], "is_fallback": False}
    ]
    for fb in decision.get("fallbackChain", []):
        targets.append({"provider": fb["provider"], "model": fb["modelId"], "is_fallback": True})

    errors: list[Exception] = []
    tokens_yielded = 0
    first_target = targets[0]

    # If APInex quota exhausted during pre-flight decision, notify user
    if "APInex GPT-6 Luna has reached its daily token limit" in decision.get("reason", ""):
        yield "data: [STATUS] APInex GPT-6 Luna has reached its daily token limit. CodeBrain has switched to another available AI model.\n\n"

    for idx, target in enumerate(targets):
        prov_name = target["provider"]
        model_name = target["model"]
        is_fb = target["is_fallback"]
        t0 = time.time()
        prov_instance = _get_provider(prov_name)
        stream_started = False

        if is_fb and first_target["provider"] == "apinex" and idx == 1 and not tokens_yielded:
            prev_err = str(errors[0]) if errors else ""
            if "daily token limit" in prev_err.lower() or "quota" in prev_err.lower() or "budget" in prev_err.lower():
                yield "data: [STATUS] APInex GPT-6 Luna has reached its daily token limit. CodeBrain has switched to another available AI model.\n\n"
            else:
                yield "data: [STATUS] APInex unavailable. CodeBrain switched to another available AI model.\n\n"

        try:
            async for token in prov_instance.stream_chat(
                messages=messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                tokens_yielded += 1
                stream_started = True
                yield token

            latency = int((time.time() - t0) * 1000)
            record_model_success(prov_name, model_name, latency)
            _log_event(task=str(task_type), provider=prov_name, model=model_name, status="success", latency_ms=latency, is_fallback=is_fb)
            return
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("[AI] Streaming interrupted by client cancellation.")
            raise
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            record_model_error(prov_name, model_name, exc, status_code)
            latency = int((time.time() - t0) * 1000)
            _log_event(
                task=str(task_type),
                provider=prov_name,
                model=model_name,
                status=status_code or "error",
                latency_ms=latency,
                is_fallback=is_fb,
                error_cat=exc.__class__.__name__,
            )
            errors.append(exc)

            # If interrupted mid-stream (already yielded tokens), do NOT restart a duplicate stream
            if stream_started and tokens_yielded > 0:
                yield f"\n\n[ERROR: Stream interrupted ({exc}). Please retry.]\n"
                return

    # All targets in chain failed pre-stream
    last_fb = targets[1] if len(targets) > 1 else None
    last_err = errors[-1] if errors else Exception("Streaming failed")
    first_err = errors[0] if errors else last_err
    diag_msg = _format_all_providers_failed_message(
        first_target["provider"], first_target["model"], first_err,
        last_fb["provider"] if last_fb else None, last_fb["model"] if last_fb else None, last_err,
    )
    yield f"\n{diag_msg}\n"


# ── Public Router API ─────────────────────────────────────────────────────────

def route_chat(
    messages: list[dict],
    task_type: Literal["chat", "code", "debug", "simple"] = "chat",
    stream: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    response_format: dict | None = None,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
):
    """
    Route a chat or code task to the appropriate provider + model.
    """
    if stream:
        return _execute_stream_chat(
            task_type=task_type,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
        )
    return _execute_sync_chat(
        task_type=task_type,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        preferred_provider=preferred_provider,
        preferred_model=preferred_model,
    )


def route_reasoning(
    messages: list[dict],
    task_type: Literal["hard_reasoning", "large_repo", "document"] = "document",
    stream: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 4096,
):
    """
    Route complex reasoning, documentation, or large codebase tasks to high-capacity reasoning models.
    """
    if stream:
        return _execute_stream_chat(
            task_type=task_type,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return _execute_sync_chat(
        task_type=task_type,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def route_vision(
    image_bytes: bytes | None = None,
    prompt: str = "",
    messages: list[dict] | None = None,
    mime_type: str = "image/png",
    stream: bool = True,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> AsyncGenerator[str, None]:
    """
    Route multimodal image/screenshot queries.
    Builds the vision content payload if image_bytes is provided.
    """
    if messages is None:
        messages = []

    if image_bytes:
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_img}"
        vision_user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or "Analyze this image and explain any errors or code issues found."},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
        # Prepend system message if any was present
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        messages = sys_msgs + [vision_user_msg]

    decision = get_model_for_task(
        task="SCREENSHOT_ANALYSIS",
        requires_vision=True,
    )
    targets = [
        {"provider": decision["provider"], "model": decision["modelId"], "is_fallback": False}
    ]
    for fb in decision.get("fallbackChain", []):
        targets.append({"provider": fb["provider"], "model": fb["modelId"], "is_fallback": True})

    errors: list[Exception] = []
    tokens_yielded = 0
    first_target = targets[0]

    for target in targets:
        prov_name = target["provider"]
        model_name = target["model"]
        is_fb = target["is_fallback"]
        t0 = time.time()
        prov_instance = _get_provider(prov_name)
        stream_started = False

        try:
            async for token in prov_instance.stream_vision(
                messages=messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                tokens_yielded += 1
                stream_started = True
                yield token

            latency = int((time.time() - t0) * 1000)
            record_model_success(prov_name, model_name, latency)
            _log_event(task="vision", provider=prov_name, model=model_name, status="success", latency_ms=latency, is_fallback=is_fb)
            return
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            record_model_error(prov_name, model_name, exc, status_code)
            latency = int((time.time() - t0) * 1000)
            _log_event(
                task="vision",
                provider=prov_name,
                model=model_name,
                status=status_code or "error",
                latency_ms=latency,
                is_fallback=is_fb,
                error_cat=exc.__class__.__name__,
            )
            errors.append(exc)

            if stream_started and tokens_yielded > 0:
                yield f"\n\n[ERROR: Vision stream interrupted ({exc}). Please retry.]\n"
                return

    last_fb = targets[1] if len(targets) > 1 else None
    last_err = errors[-1] if errors else Exception("Vision failed")
    first_err = errors[0] if errors else last_err
    diag_msg = _format_all_providers_failed_message(
        first_target["provider"], first_target["model"], first_err,
        last_fb["provider"] if last_fb else None, last_fb["model"] if last_fb else None, last_err,
    )
    yield f"\n{diag_msg}\n"


async def route_transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Route audio transcription (Speech-to-Text).
    """
    routes = get_routing_table()
    route = routes["transcribe"]
    primary = route.primary
    fallback = route.fallback

    t0 = time.time()
    primary_prov = _get_provider(primary.provider)
    try:
        res = await primary_prov.transcribe(audio_bytes=audio_bytes, model=primary.model, filename=filename)
        latency = int((time.time() - t0) * 1000)
        _log_event(task="transcribe", provider=primary.provider, model=primary.model, status="success", latency_ms=latency)
        return res
    except Exception as exc:
        latency = int((time.time() - t0) * 1000)
        status_code = getattr(exc, "status_code", "error")
        _log_event(task="transcribe", provider=primary.provider, model=primary.model, status=status_code, latency_ms=latency, error_cat=exc.__class__.__name__)
        if not fallback:
            raise AllProvidersFailedError("Audio transcription unavailable.", errors=[exc]) from exc

    t1 = time.time()
    fallback_prov = _get_provider(fallback.provider)
    try:
        res = await fallback_prov.transcribe(audio_bytes=audio_bytes, model=fallback.model, filename=filename)
        latency = int((time.time() - t1) * 1000)
        _log_event(task="transcribe", provider=fallback.provider, model=fallback.model, status="success", latency_ms=latency, is_fallback=True)
        return res
    except Exception as exc:
        latency = int((time.time() - t1) * 1000)
        status_code = getattr(exc, "status_code", "error")
        _log_event(task="transcribe", provider=fallback.provider, model=fallback.model, status=status_code, latency_ms=latency, is_fallback=True, error_cat=exc.__class__.__name__)
        raise AllProvidersFailedError("Both audio transcription providers are temporarily unavailable.", errors=[exc]) from exc


async def route_tts(text: str) -> bytes:
    """
    Route text-to-speech audio synthesis.
    """
    routes = get_routing_table()
    route = routes["tts"]
    primary = route.primary
    primary_prov = _get_provider(primary.provider)
    return await primary_prov.tts(text=text, model=primary.model)


# ── Unified AI Client Interfaces ──────────────────────────────────────────────

def generate_text(
    prompt: str,
    system_prompt: str | None = None,
    task: TaskType = "chat",
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Unified synchronous text generation interface."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return route_chat(
        messages=messages,
        task_type=task,
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def generate_code(
    prompt: str,
    context: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str:
    """Unified code generation interface routed to code-specialized model."""
    messages = [
        {
            "role": "system",
            "content": "You are an expert software engineer. Provide precise, production-grade code without unnecessary preamble.",
        }
    ]
    if context:
        messages.append({"role": "user", "content": f"Context:\n```\n{context}\n```\n\nTask:\n{prompt}"})
    else:
        messages.append({"role": "user", "content": prompt})

    return route_chat(
        messages=messages,
        task_type="code",
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def stream_text(
    prompt: str,
    system_prompt: str | None = None,
    task: TaskType = "chat",
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> AsyncGenerator[str, None]:
    """Unified streaming text generation interface."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    generator = route_chat(
        messages=messages,
        task_type=task,
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    async for chunk in generator:
        yield chunk


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Unified audio speech-to-text interface."""
    return await route_transcribe(audio_bytes=audio_bytes, filename=filename)


def test_provider_connection(
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """
    Test connection to a specified AI provider with latency measurement.
    Does not leak secrets in output.
    """
    import httpx
    p = provider.lower().strip()
    t0 = time.time()

    if p == "nvidia":
        key = api_key or os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY") or ""
        if not key:
            return {"status": "error", "provider": "nvidia", "message": "NVIDIA API key not provided or configured."}
        target_model = model or "glm-5-3"
        resolved_model = _PROVIDERS["nvidia"]._resolve_model(target_model) if "nvidia" in _PROVIDERS else target_model
        try:
            resp = httpx.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": resolved_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=12.0,
            )
            lat = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return {"status": "success", "provider": "nvidia", "model": target_model, "latency_ms": lat, "message": "NVIDIA connected successfully."}
            return {"status": "error", "provider": "nvidia", "latency_ms": lat, "message": f"NVIDIA rejected request ({resp.status_code}): {resp.text[:120]}"}
        except Exception as exc:
            return {"status": "error", "provider": "nvidia", "message": f"NVIDIA connection failed: {exc}"}

    elif p == "groq":
        key = api_key or os.environ.get("GROQ_API_KEY") or ""
        if not key:
            return {"status": "error", "provider": "groq", "message": "Groq API key not provided or configured."}
        target_model = model or "llama-3.3-70b-versatile"
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": target_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=12.0,
            )
            lat = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return {"status": "success", "provider": "groq", "model": target_model, "latency_ms": lat, "message": "Groq connected successfully."}
            return {"status": "error", "provider": "groq", "latency_ms": lat, "message": f"Groq rejected request ({resp.status_code}): {resp.text[:120]}"}
        except Exception as exc:
            return {"status": "error", "provider": "groq", "message": f"Groq connection failed: {exc}"}

    elif p in ("custom", "openai-compatible"):
        url = (base_url or os.environ.get("CUSTOM_AI_BASE_URL") or "").rstrip("/")
        if not url:
            return {"status": "error", "provider": "openai-compatible", "message": "OpenAI-Compatible Base URL is required."}
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        target_model = model or os.environ.get("CUSTOM_AI_MODEL") or "default"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            resp = httpx.post(
                url,
                headers=headers,
                json={
                    "model": target_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
                timeout=10.0,
            )
            lat = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return {"status": "success", "provider": "openai-compatible", "model": target_model, "latency_ms": lat, "message": f"OpenAI-Compatible endpoint ({url}) connected successfully."}
            return {"status": "error", "provider": "openai-compatible", "latency_ms": lat, "message": f"Endpoint returned status {resp.status_code}: {resp.text[:120]}"}
        except Exception as exc:
            return {"status": "error", "provider": "openai-compatible", "message": f"Could not connect to endpoint ({url}): {exc}"}

    elif p == "anthropic-compatible":
        url = (base_url or "").rstrip("/")
        if not url:
            return {"status": "error", "provider": "anthropic-compatible", "message": "Anthropic-Compatible Base URL is required."}
        if not url.endswith("/messages"):
            url = f"{url}/messages"
        target_model = model or "default"
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if api_key:
            headers["x-api-key"] = api_key
        try:
            resp = httpx.post(
                url,
                headers=headers,
                json={
                    "model": target_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 10,
                },
                timeout=12.0,
            )
            lat = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return {"status": "success", "provider": "anthropic-compatible", "model": target_model, "latency_ms": lat, "message": f"Anthropic-Compatible endpoint ({url}) connected successfully."}
            return {"status": "error", "provider": "anthropic-compatible", "latency_ms": lat, "message": f"Endpoint returned status {resp.status_code}: {resp.text[:120]}"}
        except Exception as exc:
            return {"status": "error", "provider": "anthropic-compatible", "message": f"Could not connect to Anthropic-Compatible endpoint ({url}): {exc}"}

    return {"status": "error", "provider": p, "message": f"Unsupported provider '{provider}'. Supported: 'nvidia', 'groq', 'openai-compatible', 'anthropic-compatible'."}


def complete(
    task_type: TaskType | str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
    response_format: dict | None = None,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
    context_size: int = 0,
) -> dict[str, Any]:
    """Execute synchronous chat completion and return {'content': ...} dict."""
    content = _execute_chat(
        task_type=task_type,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        preferred_provider=preferred_provider,
        preferred_model=preferred_model,
        context_size=context_size,
    )
    return {"content": content}


class _AIRouterProxy:
    def complete(self, *args, **kwargs) -> dict[str, Any]:
        return complete(*args, **kwargs)

    def chat(self, *args, **kwargs) -> str:
        return _execute_chat(*args, **kwargs)

    def stream_chat(self, *args, **kwargs):
        return _execute_stream_chat(*args, **kwargs)


_ROUTER_INSTANCE = _AIRouterProxy()


def get_ai_router() -> _AIRouterProxy:
    return _ROUTER_INSTANCE


