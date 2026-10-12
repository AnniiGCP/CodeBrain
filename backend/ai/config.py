"""
backend/ai/config.py
--------------------
Configuration and routing matrix for the centralized AI router.
Primary Provider: NVIDIA NIM (with specialized models for code, reasoning, multimodal).
Fallback Provider: Groq (ultra-low latency inference, Whisper transcription).
Additional Providers: OpenRouter, Custom OpenAI-compatible endpoints, Anthropic-compatible endpoints.

Policy:
  NVIDIA NIM = Primary provider
  Groq = Fallback provider
  Model selected by Task + Context Size + Modality + Reasoning/Tool Requirements + Model Health.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

ProviderType = Literal["groq", "nvidia", "custom", "openai-compatible", "anthropic-compatible", "apinex"]
TaskType = Literal[
    "chat",
    "code",
    "debug",
    "simple",
    "hard_reasoning",
    "large_repo",
    "document",
    "vision",
    "transcribe",
    "tts",
    "realtime_voice",
]


@dataclass(frozen=True)
class RouteTarget:
    provider: ProviderType
    model: str


@dataclass(frozen=True)
class TaskRoute:
    primary: RouteTarget
    fallback: RouteTarget | None = None


# ── EXACT REQUESTED NVIDIA & GROQ MODEL REGISTRIES ───────────────────────────
from ai.registry import (
    CURATED_NVIDIA_MODELS as NVIDIA_MODEL_REGISTRY,
    DEFAULT_GROQ_FALLBACK_MODELS,
    DISPLAY_NAME_MAP,
    clean_display_name,
    get_nvidia_models,
    get_groq_models,
    get_master_ai_registry,
)


def get_large_context_threshold() -> int:
    """Character/token threshold to switch to large context reasoning."""
    return int(os.environ.get("AI_LARGE_CONTEXT_THRESHOLD", "65000"))


# ── MODEL HEALTH TRACKING ─────────────────────────────────────────────────────
# Health statuses: AVAILABLE | DEGRADED | RATE_LIMITED | UNAVAILABLE | DISABLED
_MODEL_HEALTH: Dict[str, Dict[str, Any]] = {}


def record_model_error(provider: str, model: str, error: Exception, status_code: Optional[int] = None) -> None:
    """Records transient failure with bounded backoff window."""
    now = time.time()
    key = f"{provider.lower()}:{model}"
    entry = _MODEL_HEALTH.setdefault(key, {"status": "AVAILABLE", "expires_at": 0, "error_count": 0, "last_error": ""})
    entry["error_count"] += 1
    entry["last_error"] = str(error)

    if status_code == 429 or "rate limit" in str(error).lower():
        entry["status"] = "RATE_LIMITED"
        entry["expires_at"] = now + 45.0  # 45s cool-down
    elif status_code == 404 or "not found" in str(error).lower() or "model_not_found" in str(error).lower():
        entry["status"] = "UNAVAILABLE"
        entry["expires_at"] = now + 600.0  # 10 min cool-down for nonexistent or deprecated model
    elif status_code in (500, 502, 503, 504) or "timeout" in str(error).lower() or "unavailable" in str(error).lower() or "timed out" in str(error).lower():
        entry["status"] = "UNAVAILABLE"
        entry["expires_at"] = now + 30.0  # 30s cool-down
    else:
        entry["status"] = "DEGRADED"
        entry["expires_at"] = now + 15.0


def record_model_success(provider: str, model: str, latency_ms: Optional[int] = None) -> None:
    """Resets health state on successful response."""
    key = f"{provider.lower()}:{model}"
    if key in _MODEL_HEALTH:
        _MODEL_HEALTH[key]["status"] = "AVAILABLE"
        _MODEL_HEALTH[key]["expires_at"] = 0
        _MODEL_HEALTH[key]["error_count"] = 0


def get_model_health(provider: str, model: str) -> str:
    """Returns current health status, clearing expired transient penalties."""
    now = time.time()
    key = f"{provider.lower()}:{model}"
    entry = _MODEL_HEALTH.get(key)
    if not entry:
        return "AVAILABLE"
    if entry["expires_at"] > 0 and now > entry["expires_at"]:
        entry["status"] = "AVAILABLE"
        entry["expires_at"] = 0
    return entry["status"]


# ── CENTRALIZED TASK ROUTING SPECIFICATION ────────────────────────────────────
# Baseline Routing Matrix as specified in Section 3
TASK_ROUTING_SPEC: Dict[str, Dict[str, Any]] = {
    "DOCUMENTATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "16-section professional documentation & synthesis (GLM 5.3)",
    },
    "DOCUMENTATION_REFINEMENT": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "glm-5-3-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Documentation refinement & targeted section improvement",
    },
    "PROJECT_OVERVIEW": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "High-level project overview & problem statement synthesis",
    },
    "TECHNOLOGY_STACK": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "glm-5-3-flash"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Technology stack reasoning & framework categorization",
    },
    "REPOSITORY_ANALYSIS": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Repository AST parsing, directory structure & call graph understanding",
    },
    "ARCHITECTURE": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "System architecture reasoning & multi-tier topology design",
    },
    "DIAGRAM": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Mermaid & SVG diagram specification planning",
    },
    "FLOWCHART": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Execution flowchart & request lifecycle planning",
    },
    "UML": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "UML class & sequence diagram architecture",
    },
    "API_ANALYSIS": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "glm-5-3"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "API endpoint discovery & parameter extraction",
    },
    "API_DOCUMENTATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Formal OpenAPI / endpoint specification writing",
    },
    "DATABASE_DISCOVERY": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "ORM entity scanning, tables & relationships discovery",
    },
    "DATABASE_DOCUMENTATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "ER schema documentation & entity relationship mapping",
    },
    "DEPENDENCY_DISCOVERY": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Package manifest inspection & version extraction",
    },
    "DEPENDENCY_EXPLANATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Dependency purpose & licensing analysis",
    },
    "CODEBASE_CHAT": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "glm-5-3-flash"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Repository-grounded chat & codebase question answering",
    },
    "FAST_CHAT": {
        "primary": ("nvidia", "glm-5-3-flash"),
        "alternate": ("nvidia", "glm-5-3"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Fast lightweight conversational chat & short responses",
    },
    "COMPLEX_TECHNICAL_CHAT": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Deep technical inquiry & architectural discussion",
    },
    "CODE_EXPLANATION": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "glm-5-3-flash"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Code snippet explanation & logic walkthrough",
    },
    "COMPLEX_CODE_EXPLANATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Multi-module complex algorithmic explanation",
    },
    "ERROR_ANALYSIS": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "glm-5-3"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Stack trace diagnosis & bug location investigation",
    },
    "SCREENSHOT_ANALYSIS": {
        "primary": ("nvidia", "deepseek-v4.1-flash"),
        "alternate": ("nvidia", "meta/llama-3.2-11b-vision-instruct"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Multimodal screenshot + code diagnostic analysis",
    },
    "ROOT_CAUSE_ANALYSIS": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Complex root cause analysis and issue deduction",
    },
    "CODE_FIX_PLANNING": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Patch strategy & regression avoidance planning",
    },
    "CODE_FIX": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Production-grade unified diff generation & code patch",
    },
    "MULTI_FILE_FIXING": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Cross-module multi-file coordinated code repair",
    },
    "TEST_GENERATION": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Comprehensive unit test & regression suite generation",
    },
    "TEST_FAILURE_REPAIR": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Test assertion repair & test runner debugging",
    },
    "DOCKER": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Dockerfile & docker-compose optimization",
    },
    "KUBERNETES": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Kubernetes manifest, Helm & cluster configuration",
    },
    "GITHUB_ACTIONS": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "GitHub Actions CI/CD pipeline automation",
    },
    "AZURE_DEVOPS": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Azure DevOps pipeline configuration",
    },
    "CI_CD": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "CI/CD workflow debugging & build pipeline fix",
    },
    "TERRAFORM": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Infrastructure-as-Code Terraform reasoning",
    },
    "GIT": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Git branch, merge conflict, and commit reasoning",
    },
    "COMMIT_MESSAGE": {
        "primary": ("nvidia", "glm-5-3-flash"),
        "alternate": ("nvidia", "glm-5-3"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Conventional commit message generation from diff",
    },
    "README": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Publication-grade project README.md synthesis",
    },
    "SUMMARY": {
        "primary": ("nvidia", "glm-5-3-flash"),
        "alternate": ("nvidia", "glm-5-3"),
        "fallback": ("groq", "openai/gpt-oss-20b"),
        "reason": "Concise summary & brief code breakdown",
    },
    "COMPLEX_SUMMARY": {
        "primary": ("nvidia", "glm-5-3"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Executive multi-dimensional codebase summary",
    },
    "LARGE_REPOSITORY_ANALYSIS": {
        "primary": ("nvidia", "nemotron-3-ultra-550b-a55b"),
        "alternate": ("nvidia", "deepseek-v4.1-flash"),
        "fallback": ("groq", "openai/gpt-oss-120b"),
        "reason": "Extremely large repository reasoning & multi-file context",
    },
}

# Task alias mapping for normalization
_TASK_ALIAS_MAP: Dict[str, str] = {
    "chat": "CODEBASE_CHAT",
    "fast_chat": "FAST_CHAT",
    "code": "CODE_FIX",
    "debug": "ERROR_ANALYSIS",
    "simple": "FAST_CHAT",
    "hard_reasoning": "COMPLEX_TECHNICAL_CHAT",
    "large_repo": "LARGE_REPOSITORY_ANALYSIS",
    "document": "DOCUMENTATION",
    "vision": "SCREENSHOT_ANALYSIS",
    "screenshot": "SCREENSHOT_ANALYSIS",
    "readme": "README",
    "cicd": "CI_CD",
    "ci_cd": "CI_CD",
    "github_actions": "GITHUB_ACTIONS",
    "docker": "DOCKER",
    "kubernetes": "KUBERNETES",
    "terraform": "TERRAFORM",
    "git": "GIT",
    "commit": "COMMIT_MESSAGE",
    "summary": "SUMMARY",
    "diagram": "DIAGRAM",
    "architecture": "ARCHITECTURE",
    "overview": "PROJECT_OVERVIEW",
}


def get_model_for_task(
    task: str,
    context_size: int = 0,
    requires_vision: bool = False,
    requires_tools: bool = False,
    complexity: str = "normal",
    user_preferred_provider: Optional[str] = None,
    user_preferred_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Centralized Model Routing Engine.
    Allocates primary model, alternate model, and fallback chain by:
      task + context_size + modality (vision) + tool requirements + model health.

    Returns:
      {
        "provider": str,
        "modelId": str,
        "displayName": str,
        "reason": str,
        "fallbackChain": [ {"provider": ..., "modelId": ..., "displayName": ..., "reason": ...}, ... ],
        "healthStatus": str,
        "task": str,
      }
    """
    raw_task = task.strip().upper()
    norm_task = _TASK_ALIAS_MAP.get(task.strip().lower(), raw_task)
    if norm_task not in TASK_ROUTING_SPEC:
        norm_task = "CODEBASE_CHAT"

    spec = TASK_ROUTING_SPEC[norm_task]
    primary_prov, primary_model = spec["primary"]
    alt_prov, alt_model = spec["alternate"]
    fb_prov, fb_model = spec["fallback"]
    reason = spec["reason"]

    # 0. Primary Provider Policy (APInex -> NVIDIA -> Groq)
    # Configurable via AI_PRIMARY_PROVIDER env var ('apinex', 'nvidia', 'groq').
    # Defaults to 'apinex' when APInex is configured with an API key and enabled.
    def_prov = os.environ.get("AI_PRIMARY_PROVIDER", "").strip().lower()
    if not def_prov:
        from ai.quota_manager import get_usage
        if get_usage().get("configured"):
            def_prov = "apinex"
        else:
            def_prov = "nvidia"

    if def_prov == "apinex":
        apinex_model = os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna")
        orig_primary_prov, orig_primary_model = primary_prov, primary_model
        primary_prov = "apinex"
        primary_model = apinex_model
        alt_prov, alt_model = orig_primary_prov, orig_primary_model
        reason = f"Primary provider APInex ({primary_model}) allocated for {norm_task}; fallback to NVIDIA then Groq."

    # 1. Vision modality override
    if requires_vision:
        primary_prov, primary_model = "nvidia", "deepseek-v4.1-flash"
        alt_prov, alt_model = "nvidia", "meta/llama-3.2-11b-vision-instruct"
        fb_prov, fb_model = "groq", "openai/gpt-oss-120b"
        reason = "Multimodal visual reasoning requested; allocated DeepSeek V4.1 Flash (Vision primary)."

    # 2. Context size threshold override (>65,000 tokens)
    large_thresh = get_large_context_threshold()
    if context_size > large_thresh:
        primary_prov, primary_model = "nvidia", "nemotron-3-ultra-550b-a55b"
        alt_prov, alt_model = "nvidia", "deepseek-v4.1-flash"
        fb_prov, fb_model = "groq", "openai/gpt-oss-120b"
        reason = f"Context size ({context_size} tokens) exceeds {large_thresh} threshold; allocated Nemotron 3 Ultra for large context reasoning."

    # 3. User custom endpoint primacy rule & manual selection handling
    # If not explicitly passed, inspect the active authenticated user's preferred settings
    if not user_preferred_provider:
        try:
            from auth import (
                current_user_preferred_provider,
                current_user_preferred_model,
                current_user_custom_model,
                current_user_anthropic_compatible_model,
            )
            ctx_prov = current_user_preferred_provider.get(None)
            ctx_model = current_user_preferred_model.get(None)
            if ctx_prov:
                user_preferred_provider = ctx_prov
                if not user_preferred_model:
                    if ctx_model:
                        user_preferred_model = ctx_model
                    elif ctx_prov in ("openai-compatible", "custom"):
                        user_preferred_model = current_user_custom_model.get(None)
                    elif ctx_prov == "anthropic-compatible":
                        user_preferred_model = current_user_anthropic_compatible_model.get(None)

                # Authoritative Issue-Fixing Routing Rule:
                # The chat panel's generic default provider ('nvidia' / 'groq') must NOT override
                # the issue-fixing priority policy (APInex -> NVIDIA -> Groq).
                # Only explicit custom endpoints ('openai-compatible', 'anthropic-compatible', 'custom')
                # or explicit caller arguments take precedence.
                if norm_task == "CODE_FIX" and ctx_prov in ("nvidia", "groq", "auto", "default", None):
                    user_preferred_provider = None
                    user_preferred_model = None
        except Exception:
            pass

    if user_preferred_provider and user_preferred_provider.strip():
        u_prov = user_preferred_provider.lower().strip()
        u_model = (user_preferred_model or "").strip()

        if u_prov != "auto" and u_prov not in ("", "system", "system_default", "default"):
            # Check vision capability compatibility
            if requires_vision and u_model and u_model not in ("deepseek-v4.1-flash", "meta/llama-3.2-11b-vision-instruct"):
                reason = f"User selected '{u_model}' which lacks vision support; routed to DeepSeek V4.1 Flash for image analysis."
            elif u_prov == "apinex":
                # Check quota status and health for APInex
                from ai.quota_manager import check_quota
                can_proceed, q_reason, _ = check_quota(estimated_tokens=500)
                a_health = get_model_health("apinex", u_model or "free/gpt-6-luna")
                if not can_proceed:
                    logger.info("[ROUTER] APInex hard limit enforced and daily quota exhausted. Falling back to NVIDIA / Groq.")
                    primary_prov, primary_model = spec["primary"]
                    alt_prov, alt_model = spec["alternate"]
                    fb_prov, fb_model = spec["fallback"]
                    reason = "APInex GPT-6 Luna has reached its daily token limit. CodeBrain has switched to NVIDIA."
                elif a_health in ("RATE_LIMITED", "UNAVAILABLE", "DEGRADED"):
                    logger.info("[ROUTER] APInex stopped working (%s). Promoting NVIDIA primary and Groq fallback.", a_health)
                    primary_prov, primary_model = spec["primary"]
                    alt_prov, alt_model = spec["alternate"]
                    fb_prov, fb_model = spec["fallback"]
                    reason = f"APInex stopped responding ({a_health}). CodeBrain has switched to NVIDIA."
                else:
                    orig_primary_prov, orig_primary_model = spec["primary"]
                    primary_prov = "apinex"
                    primary_model = u_model or "free/gpt-6-luna"
                    alt_prov, alt_model = orig_primary_prov, orig_primary_model
                    fb_prov, fb_model = spec["fallback"]
                    reason = f"APInex primary ({primary_model}) selected."
            elif u_prov in ("openai-compatible", "anthropic-compatible", "custom"):
                # USER-PROVIDED ENDPOINT RULE:
                # User endpoints take absolute precedence across all tasks (chat, code fixing, docs)
                primary_prov = u_prov
                primary_model = u_model or ("custom-model" if u_prov != "anthropic-compatible" else "claude-3-5-sonnet")
                # Fallback to developer defaults if user endpoint fails
                alt_prov, alt_model = "apinex", os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna")
                fb_prov, fb_model = spec["primary"]
                reason = f"User-provided custom endpoint {clean_display_name(primary_model)} ({u_prov.upper()}) active as primary model across all sources."
            else:
                primary_prov = u_prov
                primary_model = u_model
                reason = f"User explicitly selected {clean_display_name(u_model)} ({u_prov.upper()})."

    # 4. Model Health Check (if primary model is currently RATE_LIMITED or UNAVAILABLE, promote alternate; if both are down, promote Groq fallback)
    p_health = get_model_health(primary_prov, primary_model)
    if p_health in ("RATE_LIMITED", "UNAVAILABLE", "DEGRADED"):
        logger.info("[ROUTER] Primary model %s:%s is %s. Promoting alternate %s:%s.", primary_prov, primary_model, p_health, alt_prov, alt_model)
        primary_prov, primary_model, alt_prov, alt_model = alt_prov, alt_model, primary_prov, primary_model
        reason += f" (Note: Primary temporarily {p_health}, alternate promoted)"

        alt_health = get_model_health(primary_prov, primary_model)
        if alt_health in ("RATE_LIMITED", "UNAVAILABLE", "DEGRADED"):
            logger.info("[ROUTER] Alternate model %s:%s is also %s. Promoting Groq fallback %s:%s.", primary_prov, primary_model, alt_health, fb_prov, fb_model)
            primary_prov, primary_model = fb_prov, fb_model
            reason += f" (Note: Primary & Alternate unavailable, Groq fallback promoted)"

    # 5. Build Fallback Chain
    fallback_chain: List[Dict[str, str]] = []
    
    # Alternate target
    if (alt_prov, alt_model) != (primary_prov, primary_model):
        fallback_chain.append({
            "provider": alt_prov,
            "modelId": alt_model,
            "displayName": clean_display_name(alt_model),
            "reason": f"Alternate model for {norm_task}",
        })

    # Groq Engineering / Fast Fallback
    if (fb_prov, fb_model) != (primary_prov, primary_model):
        fallback_chain.append({
            "provider": fb_prov,
            "modelId": fb_model,
            "displayName": clean_display_name(fb_model),
            "reason": f"Primary Groq fallback for {norm_task}",
        })

    # Secondary Groq Fallback (Qwen 3.8 27B for reasoning or GPT-OSS 20B for fast)
    sec_fb_model = "qwen/qwen3.8-27b" if "120b" in fb_model.lower() else "openai/gpt-oss-20b"
    if sec_fb_model not in (primary_model, alt_model, fb_model):
        fallback_chain.append({
            "provider": "groq",
            "modelId": sec_fb_model,
            "displayName": clean_display_name(sec_fb_model),
            "reason": "Secondary Groq reasoning fallback",
        })

    return {
        "provider": primary_prov,
        "modelId": primary_model,
        "displayName": clean_display_name(primary_model),
        "reason": reason,
        "fallbackChain": fallback_chain,
        "healthStatus": p_health,
        "task": norm_task,
    }


# CamelCase alias
getModelForTask = get_model_for_task


# ── BACKWARD-COMPATIBLE ROUTING TABLE ─────────────────────────────────────────

def get_routing_table() -> dict[str, TaskRoute]:
    """
    Returns the task routing table with env-configured model names.
    Supports user preferred provider and model overrides via contextvars.
    Preserves backward compatibility for existing test suites.
    """
    pref_provider: str | None = None
    pref_model: str | None = None
    try:
        from auth import current_user_preferred_model, current_user_preferred_provider
        pref_provider = current_user_preferred_provider.get()
        pref_model = current_user_preferred_model.get()
    except Exception:
        pass

    # Primary NVIDIA models
    nvidia_chat_model = os.environ.get("AI_CHAT_MODEL", "glm-5-3")
    nvidia_code_model = os.environ.get("AI_CODE_MODEL", "glm-5-3")
    nvidia_fast_model = os.environ.get("AI_FAST_MODEL", "glm-5-3-flash")
    nvidia_debug_model = os.environ.get("AI_DEBUG_MODEL", "deepseek-v4.1-flash")
    nvidia_reasoning_model = os.environ.get("AI_REASONING_MODEL", "deepseek-v4.1-flash")
    nvidia_large_repo_model = os.environ.get("AI_LARGE_REPO_MODEL", "nemotron-3-ultra-550b-a55b")
    nvidia_document_model = os.environ.get("AI_DOCUMENT_MODEL", "glm-5-3")
    nvidia_vision_model = os.environ.get("AI_VISION_PRIMARY_MODEL", "meta/llama-3.2-11b-vision-instruct")

    # Fallback Groq models (active Groq endpoints)
    groq_primary_chat = os.environ.get("AI_GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
    groq_code_model = os.environ.get("AI_GROQ_CODE_MODEL", "openai/gpt-oss-120b")
    groq_simple_model = os.environ.get("AI_SIMPLE_MODEL", "openai/gpt-oss-20b")
    groq_vision_fallback = os.environ.get("AI_VISION_FALLBACK_MODEL", "llama-3.2-11b-vision-instruct")

    # STT / TTS models (dedicated models, never LLMs)
    stt_primary = os.environ.get("AI_STT_MODEL", "whisper-large-v3-turbo")
    tts_primary = os.environ.get("AI_TTS_MODEL", "canopylabs/orpheus-v1-english")

    table: dict[str, TaskRoute] = {
        "chat": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_chat_model),
            fallback=RouteTarget(provider="groq", model=groq_primary_chat),
        ),
        "code": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_code_model),
            fallback=RouteTarget(provider="groq", model=groq_code_model),
        ),
        "debug": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_debug_model),
            fallback=RouteTarget(provider="groq", model=groq_code_model),
        ),
        "simple": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_fast_model),
            fallback=RouteTarget(provider="groq", model=groq_simple_model),
        ),
        "hard_reasoning": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_reasoning_model),
            fallback=RouteTarget(provider="groq", model=groq_primary_chat),
        ),
        "large_repo": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_large_repo_model),
            fallback=RouteTarget(provider="groq", model=groq_primary_chat),
        ),
        "document": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_document_model),
            fallback=RouteTarget(provider="groq", model=groq_primary_chat),
        ),
        "vision": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_vision_model),
            fallback=RouteTarget(provider="groq", model=groq_vision_fallback),
        ),
        "transcribe": TaskRoute(
            primary=RouteTarget(provider="groq", model=stt_primary),
            fallback=None,
        ),
        "tts": TaskRoute(
            primary=RouteTarget(provider="groq", model=tts_primary),
            fallback=None,
        ),
        "realtime_voice": TaskRoute(
            primary=RouteTarget(provider="nvidia", model=nvidia_chat_model),
            fallback=RouteTarget(provider="groq", model=groq_primary_chat),
        ),
    }

    # If user selected an explicit preferred provider
    if pref_provider in ("nvidia", "groq", "apinex", "openai-compatible", "anthropic-compatible", "custom"):
        chosen_p: ProviderType = "openai-compatible" if pref_provider == "custom" else pref_provider  # type: ignore
        for task in ("chat", "code", "debug", "simple", "hard_reasoning", "large_repo", "document", "vision"):
            target_model = pref_model
            if not target_model:
                if chosen_p == "nvidia":
                    target_model = nvidia_chat_model
                elif chosen_p == "groq":
                    target_model = groq_primary_chat
                elif chosen_p == "apinex":
                    target_model = os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna")
                elif chosen_p == "openai-compatible":
                    target_model = os.environ.get("CUSTOM_AI_MODEL", "default")
                elif chosen_p == "anthropic-compatible":
                    target_model = "default"

            fallback_target = (
                RouteTarget(provider="groq", model=groq_primary_chat)
                if chosen_p != "groq"
                else RouteTarget(provider="nvidia", model=nvidia_chat_model)
            )

            table[task] = TaskRoute(
                primary=RouteTarget(provider=chosen_p, model=target_model),
                fallback=fallback_target,
            )

    return table
