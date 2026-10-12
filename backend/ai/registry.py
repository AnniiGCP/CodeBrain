"""
backend/ai/registry.py
----------------------
Master AI Provider and Model Registry.
Separates:
  - provider ID ("nvidia", "groq", "anthropic", "openai-compatible", "anthropic-compatible")
  - provider display name ("NVIDIA", "Groq", "Anthropic", "OpenAI-Compatible", "Anthropic-Compatible")
  - model ID (e.g. "glm-5-3", "llama-3.3-70b-versatile", "claude-3-5-sonnet-20241022")
  - model display name (e.g. "GLM 5.3", "Llama 3.3 70B", "Claude 3.5 Sonnet")
  - capabilities, context window, badge, and status.

Strict Rules:
  - Provider display name NEVER overwrites model display name.
  - "NVIDIA NIM" is NEVER used as a model display name.
  - OpenRouter is NEVER included in user-facing provider configuration.
  - Curated preferred models are guaranteed available with authentic provider names.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── MODEL ALIAS / UPSTREAM MAPPING FOR NVIDIA NIM ────────────────────────────
NVIDIA_UPSTREAM_MAP: Dict[str, str] = {
    "glm-5-3": "z-ai/glm-5.3",
    "glm-5-3-flash": "z-ai/glm-5.3-flash",
    "deepseek-v4.1-flash": "deepseek-ai/deepseek-v4.1-flash",
    "nemotron-3-ultra-550b-a55b": "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-ultra-550b-a55b": "nvidia/nemotron-3-ultra-550b-a55b",
    "meta/llama-3.2-11b-vision-instruct": "meta/llama-3.2-11b-vision-instruct",
}

# ── KNOWN DISPLAY NAMES MAPPING ──────────────────────────────────────────────
DISPLAY_NAME_MAP: Dict[str, str] = {
    # NVIDIA
    "glm-5-3": "GLM 5.3",
    "z-ai/glm-5.3": "GLM 5.3",
    "glm-5-3-flash": "GLM 5.3 Flash",
    "z-ai/glm-5.3-flash": "GLM 5.3 Flash",
    "deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "deepseek-ai/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra",
    "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra",
    "meta/llama-3.2-11b-vision-instruct": "Llama 3.2 11B Vision",
    "meta/llama-3.1-70b-instruct": "Llama 3.1 70B Instruct",
    "meta/llama-3.1-8b-instruct": "Llama 3.1 8B Instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct": "Llama 3.1 Nemotron 70B",
    "nvidia/llama-3.1-nemotron-51b-instruct": "Llama 3.1 Nemotron 51B",
    
    # Groq
    "openai/gpt-oss-120b": "GPT-OSS 120B",
    "openai/gpt-oss-20b": "GPT-OSS 20B",
    "qwen/qwen3.8-27b": "Qwen 3.8 27B",
    "allam-2-7b": "Allam 2 7B",
    "llama-3.3-70b-versatile": "Llama 3.3 70B",
    "llama-3.1-8b-instant": "Llama 3.1 8B Instant",
    "mixtral-8x7b-32768": "Mixtral 8x7B",
    "meta-llama/llama-3.3-70b-instruct": "Llama 3.3 70B",
    
    # Anthropic
    "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
    "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
    "claude-3-opus-20240229": "Claude 3 Opus",
    "claude-3-sonnet-20240229": "Claude 3 Sonnet",
    "claude-3-haiku-20240307": "Claude 3 Haiku",

    # APInex
    "free/gpt-6-luna": "GPT-6 Luna",
    "gpt-6-luna": "GPT-6 Luna",
}

# ── CURATED NVIDIA MODELS REGISTRY ───────────────────────────────────────────
CURATED_NVIDIA_MODELS: List[Dict[str, Any]] = [
    {
        "id": "glm-5-3",
        "displayName": "GLM 5.3",
        "providerId": "nvidia",
        "providerDisplayName": "NVIDIA",
        "capabilities": ["chat", "reasoning", "coding", "tool_calling"],
        "contextWindow": 131072,
        "badge": "RECOMMENDED",
        "status": "AVAILABLE",
        "source": "curated",
        "upstreamModelId": "z-ai/glm-5.3",
    },
    {
        "id": "glm-5-3-flash",
        "displayName": "GLM 5.3 Flash",
        "providerId": "nvidia",
        "providerDisplayName": "NVIDIA",
        "capabilities": ["chat", "reasoning", "coding"],
        "contextWindow": 131072,
        "badge": "FAST",
        "status": "AVAILABLE",
        "source": "curated",
        "upstreamModelId": "z-ai/glm-5.3-flash",
    },
    {
        "id": "deepseek-v4.1-flash",
        "displayName": "DeepSeek V4.1 Flash",
        "providerId": "nvidia",
        "providerDisplayName": "NVIDIA",
        "capabilities": ["chat", "coding", "reasoning"],
        "contextWindow": 65536,
        "badge": "REASONING / CODING",
        "status": "AVAILABLE",
        "source": "curated",
        "upstreamModelId": "deepseek-ai/deepseek-v4.1-flash",
    },
    {
        "id": "nemotron-3-ultra-550b-a55b",
        "displayName": "Nemotron 3 Ultra",
        "providerId": "nvidia",
        "providerDisplayName": "NVIDIA",
        "capabilities": ["chat", "reasoning", "coding", "long_context"],
        "contextWindow": 65536,
        "badge": "LONG CONTEXT / CODING",
        "status": "AVAILABLE",
        "source": "curated",
        "upstreamModelId": "nvidia/nemotron-3-ultra-550b-a55b",
    },
    {
        "id": "meta/llama-3.2-11b-vision-instruct",
        "displayName": "Llama 3.2 11B Vision",
        "providerId": "nvidia",
        "providerDisplayName": "NVIDIA",
        "capabilities": ["chat", "reasoning", "coding", "vision"],
        "contextWindow": 131072,
        "badge": "VISION",
        "status": "AVAILABLE",
        "source": "curated",
        "upstreamModelId": "meta/llama-3.2-11b-vision-instruct",
    },
]

# ── KNOWN GROQ MODELS (FALLBACK CACHE) ─────────────────────────────────────────
DEFAULT_GROQ_FALLBACK_MODELS: List[Dict[str, Any]] = [
    {
        "id": "openai/gpt-oss-120b",
        "displayName": "GPT-OSS 120B",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "coding", "reasoning"],
        "contextWindow": 131072,
        "badge": "ENGINEERING FALLBACK",
        "status": "AVAILABLE",
        "source": "curated",
    },
    {
        "id": "openai/gpt-oss-20b",
        "displayName": "GPT-OSS 20B",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "coding", "fast"],
        "contextWindow": 131072,
        "badge": "FAST FALLBACK",
        "status": "AVAILABLE",
        "source": "curated",
    },
    {
        "id": "qwen/qwen3.8-27b",
        "displayName": "Qwen 3.8 27B",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "coding", "reasoning"],
        "contextWindow": 131072,
        "badge": "REASONING FALLBACK",
        "status": "AVAILABLE",
        "source": "curated",
    },
    {
        "id": "allam-2-7b",
        "displayName": "Allam 2 7B",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "fast"],
        "contextWindow": 32768,
        "badge": "LIGHTWEIGHT",
        "status": "AVAILABLE",
        "source": "curated",
    },
    {
        "id": "llama-3.3-70b-versatile",
        "displayName": "Llama 3.3 70B",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "coding", "reasoning"],
        "contextWindow": 131072,
        "badge": "FALLBACK",
        "status": "AVAILABLE",
        "source": "curated",
    },
    {
        "id": "llama-3.1-8b-instant",
        "displayName": "Llama 3.1 8B Instant",
        "providerId": "groq",
        "providerDisplayName": "Groq",
        "capabilities": ["chat", "coding", "fast"],
        "contextWindow": 131072,
        "badge": "FAST",
        "status": "AVAILABLE",
        "source": "curated",
    },
]

# In-memory discovery cache with TTL
_GROQ_DISCOVERY_CACHE: Dict[str, Any] = {"timestamp": 0, "models": []}
_NVIDIA_DISCOVERY_CACHE: Dict[str, Any] = {"timestamp": 0, "models": []}


def clean_display_name(model_id: str) -> str:
    """Generate a clean, authentic display name from a raw model ID."""
    if model_id in DISPLAY_NAME_MAP:
        return DISPLAY_NAME_MAP[model_id]

    # Strip vendor prefix if present (e.g., "meta/", "z-ai/", "openai/")
    base = model_id.split("/")[-1]
    if base in DISPLAY_NAME_MAP:
        return DISPLAY_NAME_MAP[base]

    # Clean formatting
    words = base.replace("-", " ").replace("_", " ").split()
    capitalized = [w.upper() if len(w) <= 3 or any(c.isdigit() for c in w) else w.capitalize() for w in words]
    return " ".join(capitalized)


def normalize_model(
    raw: Dict[str, Any] | str,
    provider_id: str,
    provider_display_name: str,
    default_badge: str = "AVAILABLE",
    default_capabilities: Optional[List[str]] = None,
    default_context: int = 32768,
    status: str = "AVAILABLE",
    source: str = "curated",
    upstream_id: Optional[str] = None,
    recommended: bool = False,
    fallback: bool = False,
) -> Dict[str, Any]:
    """
    Produce a canonical, normalized model object with all required fields.
    Both 'displayName' and 'name' are set to the real human-readable model name.
    Strictly preserves providerId and modelId.
    """
    if isinstance(raw, str):
        mid = raw.strip()
        display_name = clean_display_name(mid)
        caps = default_capabilities or ["chat", "reasoning"]
        ctx = default_context
        badge = default_badge
    else:
        mid = str(raw.get("id") or "").strip()
        display_name = raw.get("displayName") or raw.get("display_name") or clean_display_name(mid)
        caps = raw.get("capabilities") or default_capabilities or ["chat", "reasoning"]
        ctx = int(raw.get("contextWindow") or raw.get("context_window") or raw.get("context_length") or default_context)
        badge = raw.get("badge") or raw.get("recommended_for") or default_badge
        status = raw.get("status") or status
        source = raw.get("source") or source
        upstream_id = raw.get("upstreamModelId") or upstream_id
        recommended = raw.get("recommended", recommended)
        fallback = raw.get("fallback", fallback)

    # Fallback to upstream map if nvidia
    if provider_id == "nvidia" and not upstream_id:
        upstream_id = NVIDIA_UPSTREAM_MAP.get(mid)

    is_rec = recommended or badge == "RECOMMENDED" or mid == "glm-5-3"
    is_fb = fallback or badge == "FALLBACK" or mid in ("llama-3.3-70b-versatile", "openai/gpt-oss-120b")

    return {
        "id": mid,
        "modelId": mid,                        # canonical field
        "name": display_name,                 # backward compatibility
        "displayName": display_name,          # canonical display name
        "modelName": display_name,            # canonical field
        "provider": provider_id,              # backward compatibility
        "providerId": provider_id,            # canonical provider ID
        "providerName": provider_display_name, # canonical provider name
        "providerLabel": provider_display_name, # backward compatibility
        "providerDisplayName": provider_display_name, # canonical provider display name
        "capabilities": caps,
        "contextWindow": ctx,
        "context_length": ctx,                # backward compatibility
        "badge": badge,
        "recommended_for": badge,             # backward compatibility
        "status": status,
        "available": status == "AVAILABLE",
        "recommended": is_rec,
        "fallback": is_fb,
        "source": source,
        "upstreamModelId": upstream_id,
        "enabled": True,
    }


def get_nvidia_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves normalized NVIDIA models.
    STRICT USER REQUIREMENT: Only expose the exact models shown in the image:
      1. GLM 5.3 (glm-5-3)
      2. GLM 5.3 Flash (glm-5-3-flash)
      3. DeepSeek V4.1 Flash (deepseek-v4.1-flash)
      4. Nemotron 3 Ultra (nemotron-3-ultra-550b-a55b)
      5. Llama 3.2 11B Vision (meta/llama-3.2-11b-vision-instruct)
    All other models are excluded.
    """
    key = api_key or os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY") or ""
    status = "AVAILABLE" if key else "NOT_CONFIGURED"

    results: List[Dict[str, Any]] = []
    for m in CURATED_NVIDIA_MODELS:
        norm = normalize_model(
            m,
            provider_id="nvidia",
            provider_display_name="NVIDIA",
            status=status,
            source="curated",
        )
        results.append(norm)

    return results


def get_groq_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves normalized Groq models.
    Tries live dynamic discovery from Groq API (GET https://api.groq.com/openai/v1/models).
    Filters out speech (whisper) and safeguard models from LLM list.
    Deduplicates strictly and uses authentic display names and exact Groq IDs.
    """
    key = api_key or os.environ.get("GROQ_API_KEY", "")
    status = "AVAILABLE" if key else "NOT_CONFIGURED"

    import time as _t
    now = _t.time()
    results: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    # 1. Try Live discovery from Groq official models API
    if key and not key.startswith("your_"):
        if now - _GROQ_DISCOVERY_CACHE.get("timestamp", 0) < 300 and _GROQ_DISCOVERY_CACHE.get("models"):
            return _GROQ_DISCOVERY_CACHE["models"]
        else:
            url = "https://api.groq.com/openai/v1/models"
            headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
            try:
                with httpx.Client(timeout=4.0) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        for item in data:
                            mid = item.get("id", "").strip()
                            if not mid or mid in seen_ids:
                                continue
                            
                            # Filter out non-chat / audio / guard models
                            low = mid.lower()
                            if any(x in low for x in ["whisper", "guard", "safeguard", "orpheus", "distil"]):
                                continue

                            # Assign contextual badges
                            badge = "FAST"
                            if "70b" in low:
                                badge = "FALLBACK"
                            elif "120b" in low or "r1" in low or "reason" in low:
                                badge = "REASONING"
                            elif "code" in low:
                                badge = "CODING"

                            norm = normalize_model(
                                raw=mid,
                                provider_id="groq",
                                provider_display_name="Groq",
                                default_badge=badge,
                                default_capabilities=["chat", "coding"],
                                default_context=item.get("context_window", 32768) or 32768,
                                status="AVAILABLE",
                                source="discovered",
                            )
                            results.append(norm)
                            seen_ids.add(mid)

                        if results:
                            for m in DEFAULT_GROQ_FALLBACK_MODELS:
                                if m["id"] not in seen_ids:
                                    results.append(normalize_model(m, provider_id="groq", provider_display_name="Groq", status="AVAILABLE", source="curated"))
                            _GROQ_DISCOVERY_CACHE["timestamp"] = now
                            _GROQ_DISCOVERY_CACHE["models"] = results
                            return results
            except Exception as exc:
                logger.debug("Groq live model discovery skipped/failed: %s", exc)

    # 2. Fallback to authentic curated Groq model catalog when offline or key absent
    for m in DEFAULT_GROQ_FALLBACK_MODELS:
        norm = normalize_model(
            m,
            provider_id="groq",
            provider_display_name="Groq",
            status=status,
            source="curated",
        )
        results.append(norm)
    return results


def get_openai_compatible_models(
    model_override: Optional[str] = None,
    base_url: Optional[str] = None,
    display_name_override: Optional[str] = None,
    has_key: bool = False,
) -> List[Dict[str, Any]]:
    """
    Retrieves normalized OpenAI-Compatible models.
    STRICT RULE: Initially EMPTY. No default models.
    Only exposes a model when explicitly configured by the user.
    """
    configured_model = (model_override or "").strip()
    configured_url = (base_url or "").strip()

    if not configured_model or not configured_url:
        return []

    disp_name = display_name_override or clean_display_name(configured_model)
    return [
        normalize_model(
            raw={
                "id": configured_model,
                "displayName": disp_name,
                "capabilities": ["chat", "coding"],
                "contextWindow": 32768,
                "badge": "COMPATIBLE",
            },
            provider_id="openai-compatible",
            provider_display_name="OpenAI-Compatible",
            status="AVAILABLE" if (configured_url and has_key) else "NOT_CONFIGURED",
            source="user-configured",
        )
    ]


def get_anthropic_compatible_models(
    model_override: Optional[str] = None,
    base_url: Optional[str] = None,
    display_name_override: Optional[str] = None,
    has_key: bool = False,
) -> List[Dict[str, Any]]:
    """
    Retrieves normalized Anthropic-Compatible models.
    STRICT RULE: Initially EMPTY. No default models.
    Only exposes a model when explicitly configured by the user.
    """
    configured_model = (model_override or "").strip()
    configured_url = (base_url or "").strip()

    if not configured_model or not configured_url:
        return []

    disp_name = display_name_override or clean_display_name(configured_model)
    return [
        normalize_model(
            raw={
                "id": configured_model,
                "displayName": disp_name,
                "capabilities": ["chat", "coding"],
                "contextWindow": 100000,
                "badge": "COMPATIBLE",
            },
            provider_id="anthropic-compatible",
            provider_display_name="Anthropic-Compatible",
            status="AVAILABLE" if (configured_url and has_key) else "NOT_CONFIGURED",
            source="user-configured",
        )
    ]


def get_apinex_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves normalized APInex GPT-6 Luna model.
    Follows environment-based configuration:
      APINEX_API_KEY
      APINEX_BASE_URL
      APINEX_MODEL_ID (default: free/gpt-6-luna)
      APINEX_ENABLED (default: true)
      APINEX_DAILY_TOKEN_LIMIT (default: 315000)
    Strictly avoids displaying 1M context window, x3 weight, or pricing metadata in UI.
    """
    key = api_key or os.environ.get("APINEX_API_KEY", "").strip()
    enabled_str = os.environ.get("APINEX_ENABLED", "true").lower().strip()
    is_enabled = enabled_str in ("true", "1", "yes")
    has_key = bool(key and not key.startswith("your_"))

    model_id = os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna").strip() or "free/gpt-6-luna"

    try:
        from ai.quota_manager import get_usage
        usage = get_usage()
        is_exhausted = usage.get("is_exhausted", False)
    except Exception:
        is_exhausted = False

    if not is_enabled or not has_key:
        status = "NOT_CONFIGURED"
        badge = "CONFIG REQUIRED"
    elif is_exhausted:
        status = "QUOTA_EXHAUSTED"
        badge = "QUOTA EXHAUSTED"
    else:
        status = "AVAILABLE"
        badge = "DAILY QUOTA: 315K"

    return [
        normalize_model(
            raw={
                "id": model_id,
                "displayName": "GPT-6 Luna",
                "name": "GPT-6 Luna",
                "capabilities": ["chat", "reasoning", "coding"],
                "badge": badge,
                "status": status,
            },
            provider_id="apinex",
            provider_display_name="APInex",
            status=status,
            source="curated",
        )
    ]


def get_master_ai_registry(user: Any = None) -> Dict[str, Any]:
    """
    Returns the complete centralized AI Provider and Model registry.
    
    EXACT PROVIDER ARCHITECTURE:
      PRIMARY: NVIDIA
      SECONDARY / FALLBACK: Groq
      APINEX: GPT-6 Luna (OpenAI-compatible with 315K daily token quota)
      CUSTOM COMPATIBILITY:
        - OpenAI-Compatible
        - Anthropic-Compatible

    STRICT RULES:
      - Standard 'Anthropic' catalog is COMPLETELY REMOVED.
      - 'OpenRouter' is COMPLETELY REMOVED.
      - OpenAI-Compatible and Anthropic-Compatible have NO default models (initially empty).
      - NVIDIA models display their genuine human-readable names (GLM 5.3, etc.).
    """
    user_nvidia_key = None
    user_groq_key = None
    custom_model = None
    custom_url = None
    custom_display_name = None
    has_custom_key = False
    anthropic_compat_model = None
    anthropic_compat_url = None
    anthropic_compat_display_name = None
    has_anthropic_compat_key = False

    if user:
        try:
            from auth import (
                get_user_nvidia_token,
                get_user_groq_token,
                get_user_custom_ai_token,
                get_user_anthropic_compatible_token,
            )
            user_nvidia_key = get_user_nvidia_token(user)
            user_groq_key = get_user_groq_token(user)
            custom_model = getattr(user, "custom_ai_model", None)
            custom_url = getattr(user, "custom_ai_base_url", None)
            custom_display_name = getattr(user, "custom_ai_display_name", None)
            has_custom_key = bool(get_user_custom_ai_token(user))
            anthropic_compat_model = getattr(user, "anthropic_compatible_model", None)
            anthropic_compat_url = getattr(user, "anthropic_compatible_base_url", None)
            anthropic_compat_display_name = getattr(user, "anthropic_compatible_display_name", None)
            has_anthropic_compat_key = bool(get_user_anthropic_compatible_token(user))
        except Exception as exc:
            logger.debug("Failed extracting user tokens for registry: %s", exc)

    nvidia_models = get_nvidia_models(api_key=user_nvidia_key)
    groq_models = get_groq_models(api_key=user_groq_key)
    apinex_models = get_apinex_models()
    openai_compat_models = get_openai_compatible_models(
        model_override=custom_model,
        base_url=custom_url,
        display_name_override=custom_display_name,
        has_key=has_custom_key,
    )
    anthropic_compat_models = get_anthropic_compatible_models(
        model_override=anthropic_compat_model,
        base_url=anthropic_compat_url,
        display_name_override=anthropic_compat_display_name,
        has_key=has_anthropic_compat_key,
    )

    nvidia_has_key = bool(user_nvidia_key or os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY"))
    groq_has_key = bool(user_groq_key or os.environ.get("GROQ_API_KEY"))

    # APInex provider status and quota summary
    apinex_key = os.environ.get("APINEX_API_KEY", "").strip()
    apinex_enabled = os.environ.get("APINEX_ENABLED", "true").lower().strip() in ("true", "1", "yes")
    has_apinex = bool(apinex_key and not apinex_key.startswith("your_") and apinex_enabled)

    try:
        from ai.quota_manager import get_usage
        apinex_usage = get_usage()
    except Exception:
        apinex_usage = {
            "daily_limit": 315000,
            "total_tokens": 0,
            "remaining_tokens": 315000,
            "percent_used": 0.0,
            "is_exhausted": False,
            "warning": False,
        }

    if not has_apinex:
        apinex_status = "NOT_CONFIGURED"
    elif apinex_usage.get("is_exhausted", False):
        apinex_status = "QUOTA_EXHAUSTED"
    else:
        apinex_status = "AVAILABLE"

    providers = [
        {
            "id": "nvidia",
            "name": "NVIDIA",
            "displayName": "NVIDIA",
            "type": "nvidia",
            "priority": 1,
            "primary": True,
            "fallback": False,
            "status": "AVAILABLE" if nvidia_has_key else "NOT_CONFIGURED",
            "models": nvidia_models,
        },
        {
            "id": "groq",
            "name": "Groq",
            "displayName": "Groq",
            "type": "groq",
            "priority": 2,
            "primary": False,
            "fallback": True,
            "status": "AVAILABLE" if groq_has_key else "NOT_CONFIGURED",
            "models": groq_models,
        },
        {
            "id": "apinex",
            "name": "APInex",
            "displayName": "APInex",
            "type": "apinex",
            "priority": 3,
            "primary": False,
            "fallback": False,
            "status": apinex_status,
            "models": apinex_models,
            "quota": {
                "daily_limit": apinex_usage.get("daily_limit", 315000),
                "used_tokens": apinex_usage.get("total_tokens", 0),
                "remaining_tokens": apinex_usage.get("remaining_tokens", 315000),
                "percent_used": apinex_usage.get("percent_used", 0.0),
                "is_exhausted": apinex_usage.get("is_exhausted", False),
                "warning": apinex_usage.get("warning", False),
            },
        },
        {
            "id": "openai-compatible",
            "name": "OpenAI-Compatible",
            "displayName": "OpenAI-Compatible",
            "type": "openai-compatible",
            "priority": 4,
            "primary": False,
            "fallback": False,
            "status": "AVAILABLE" if (custom_url and has_custom_key) else "NOT_CONFIGURED",
            "models": openai_compat_models,
        },
        {
            "id": "anthropic-compatible",
            "name": "Anthropic-Compatible",
            "displayName": "Anthropic-Compatible",
            "type": "anthropic-compatible",
            "priority": 5,
            "primary": False,
            "fallback": False,
            "status": "AVAILABLE" if (anthropic_compat_url and has_anthropic_compat_key) else "NOT_CONFIGURED",
            "models": anthropic_compat_models,
        },
    ]

    all_models: List[Dict[str, Any]] = (
        nvidia_models + groq_models + apinex_models + openai_compat_models + anthropic_compat_models
    )

    pref_provider = getattr(user, "preferred_ai_provider", None) or "nvidia"
    pref_model = getattr(user, "preferred_ai_model", None) or "glm-5-3"

    # Validate that preferred_provider is one of the allowed providers
    if pref_provider not in ("nvidia", "groq", "apinex", "openai-compatible", "anthropic-compatible"):
        pref_provider = "nvidia"
        pref_model = "glm-5-3"

    return {
        "status": "success",
        "primary_provider": "nvidia",
        "fallback_provider": "groq",
        "preferredProvider": pref_provider,
        "preferredModel": pref_model,
        "providers": providers,
        "providers_map": {p["id"]: p for p in providers},
        "models": all_models,
    }

