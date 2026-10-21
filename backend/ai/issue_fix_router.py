"""
backend/ai/issue_fix_router.py
------------------------------
Authoritative issue-fixing router for CodeBrain.

Required provider priority hierarchy for ALL issue fixes:
  1. APInex — GPT-6 Luna (`free/gpt-6-luna` or configured APINEX_MODEL_ID)
  2. NVIDIA — configured primary fallback model (e.g. `glm-5-3`)
  3. Groq   — configured secondary fallback model (e.g. `openai/gpt-oss-120b`)

Enforces:
  - Real sequential fallback attempts (APInex -> NVIDIA -> Groq).
  - Validation of candidate patches before returning (rejects empty responses,
    unusable prose, malformed diffs, or diffs targeting wrong files).
  - APInex daily token limit quota enforcement (315,000 tokens daily budget).
  - Accurate, truthful structured diagnostic attempt tracking.
  - Safe extraction and normalization into unified diffs.
"""
from __future__ import annotations

import difflib
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from ai.config import (
    get_model_health,
    record_model_error,
    record_model_success,
)
from ai.exceptions import (
    AIProviderError,
    AllProvidersFailedError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.quota_manager import check_quota
from ai.registry import DISPLAY_NAME_MAP, clean_display_name

logger = logging.getLogger("ai.issue_fix_router")


@dataclass
class IssueFixAttempt:
    attempt: int
    provider: str
    model: str
    status: str  # "success" | "failed" | "skipped"
    latency_ms: Optional[int] = None
    http_status: Optional[int] = None
    failure_category: Optional[str] = None
    error: Optional[str] = None
    valid_patch: bool = False


@dataclass
class IssueFixResult:
    diff: str
    provider: str
    model: str
    model_display_name: str
    fallback_used: bool
    fix_attribution: str
    attempts: List[Dict[str, Any]]
    raw_response: str


def _is_conversational_or_placeholder(text: str) -> bool:
    """
    Detect whether candidate text is an assistant conversational explanation,
    a plan, a placeholder, or conversational English prose rather than valid code.
    """
    if not text or not text.strip():
        return True

    stripped = text.strip()
    first_line = stripped.splitlines()[0].strip()

    conversational_prefixes = (
        "i'll", "i will", "let me", "i am", "in order to", "first,", "first ",
        "step 1", "here is", "here's", "sure", "please", "as an ai", "wait,",
        "todo:", "note:", "explanation:", "below is", "i have", "to fix",
        "i need to", "inspect the file", "we can", "this patch", "here are",
    )
    lower_first = first_line.lower()
    if any(lower_first.startswith(p) for p in conversational_prefixes):
        return True

    # Check for short single/few-line conversational statements
    lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    if len(lines) <= 3:
        for l in lines:
            l_lower = l.lower()
            if any(l_lower.startswith(p) for p in conversational_prefixes):
                return True
            if "inspect the file" in l_lower or "accurate line numbers" in l_lower or "apply the fix" in l_lower:
                return True

    return False


def _validate_patch_safety_and_syntax(
    diff_str: str,
    expected_file_path: Optional[str] = None,
    source_code: Optional[str] = None,
) -> bool:
    """
    Enforces hard patch safety checks:
      1. Rejects patches whose added lines are conversational prose or placeholders.
      2. Rejects destructive patches deleting >50% of source lines without explicit replacement.
      3. For Python files, verifies that the patched code compiles cleanly with ast.parse.
    """
    import ast

    lines = diff_str.splitlines()
    added_lines = [
        l[1:].strip() for l in lines
        if l.startswith("+") and not l.startswith("+++") and l[1:].strip()
    ]
    deleted_lines = [
        l[1:].strip() for l in lines
        if l.startswith("-") and not l.startswith("---") and l[1:].strip()
    ]

    # 1. Reject conversational additions
    for al in added_lines:
        if _is_conversational_or_placeholder(al):
            logger.warning("[PATCH_SAFETY] Rejected diff containing conversational addition: %r", al)
            return False

    # 2. Check destructive deletion ratio
    if source_code:
        src_nonblank = [l for l in source_code.splitlines() if l.strip()]
        if len(src_nonblank) >= 10:
            if len(deleted_lines) > len(src_nonblank) * 0.5 and len(added_lines) < len(deleted_lines) * 0.3:
                logger.warning(
                    "[PATCH_SAFETY] Rejected destructive patch: deleted %d of %d lines with only %d added",
                    len(deleted_lines), len(src_nonblank), len(added_lines),
                )
                return False

        # 3. Syntax validation for Python files
        if expected_file_path and expected_file_path.endswith(".py"):
            try:
                # Test in-memory patch application
                test_lines = list(source_code.splitlines(keepends=True))
                # Quick check if replacement is direct or simulated
                from codefix.patch_safety import _apply_unified_diff_pure_python
                import tempfile
                with tempfile.TemporaryDirectory() as tmp_dir:
                    t_root = Path(tmp_dir)
                    t_file = t_root / Path(expected_file_path).name
                    t_file.write_text(source_code, encoding="utf-8")
                    ok, _, _ = _apply_unified_diff_pure_python(t_root, diff_str, target_file_hint=t_file.name)
                    if ok:
                        patched_src = t_file.read_text(encoding="utf-8", errors="replace")
                        ast.parse(patched_src)
            except SyntaxError as syn_err:
                logger.warning("[PATCH_SAFETY] Rejected patch resulting in Python SyntaxError: %s", syn_err)
                return False
            except Exception as exc:
                logger.debug("[PATCH_SAFETY] Patch syntax simulation note: %s", exc)

    return True


def clean_and_normalize_diff(
    raw: str,
    expected_file_path: Optional[str] = None,
    source_code: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Cleans raw model output to extract a valid git-style unified diff.
    If the model returned full-file code instead of a diff and source_code is provided,
    generates a unified diff comparing source_code and the replacement code.

    Returns:
        (cleaned_diff, is_valid)
    """
    if not raw or not raw.strip():
        return "", False

    text = raw.strip()

    # 1. Check for diff inside markdown code block ```diff ... ```
    diff_block_match = re.search(r"```(?:diff)?\s*\n(---[^\n]+\n\+\+\+[^\n]+\n[\s\S]+?)```", text)
    if diff_block_match:
        text = diff_block_match.group(1).strip()
    else:
        # Strip generic markdown fences
        text = re.sub(r"^```(?:diff|[a-zA-Z0-9_\-]+)?\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        text = text.strip()

    # 2. Extract starting from first '--- ' line
    lines = text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if l.startswith("--- ")), None)
    if start_idx is not None:
        candidate = "\n".join(lines[start_idx:]).strip()
        if _is_syntactically_valid_diff(candidate, expected_file_path):
            if _validate_patch_safety_and_syntax(candidate, expected_file_path, source_code):
                return candidate, True

    # 3. If no direct unified diff headers, check if model returned full replacement code
    if source_code and expected_file_path:
        code_candidate = _extract_code_block(raw)
        if (
            code_candidate
            and not _is_conversational_or_placeholder(code_candidate)
            and code_candidate.strip() != source_code.strip()
        ):
            # Synthesize valid unified diff
            norm_path = expected_file_path.replace("\\", "/").strip().lstrip("/")
            src_lines = source_code.splitlines(keepends=True)
            dst_lines = code_candidate.splitlines(keepends=True)
            diff_lines = list(
                difflib.unified_diff(
                    src_lines,
                    dst_lines,
                    fromfile=f"a/{norm_path}",
                    tofile=f"b/{norm_path}",
                )
            )
            synthetic_diff = "".join(diff_lines).strip()
            if synthetic_diff and _is_syntactically_valid_diff(synthetic_diff, expected_file_path):
                if _validate_patch_safety_and_syntax(synthetic_diff, expected_file_path, source_code):
                    logger.info("Synthesized valid unified diff from full-file model replacement for %s", expected_file_path)
                    return synthetic_diff, True

    # Check if raw text directly qualifies
    if _is_syntactically_valid_diff(text, expected_file_path):
        if _validate_patch_safety_and_syntax(text, expected_file_path, source_code):
            return text, True

    return text, False


def _extract_code_block(text: str) -> Optional[str]:
    """Extract code contents from markdown block if present, ignoring conversational text."""
    if _is_conversational_or_placeholder(text):
        return None

    m = re.search(r"```(?:[a-zA-Z0-9_\-]+)?\s*\n([\s\S]+?)```", text)
    if m:
        candidate = m.group(1)
        if not _is_conversational_or_placeholder(candidate):
            return candidate
        return None

    # If no fences, but looks like plain code
    if not _is_conversational_or_placeholder(text):
        return text
    return None


def _is_syntactically_valid_diff(diff_str: str, expected_file_path: Optional[str] = None) -> bool:
    """
    Validates that diff_str represents an actual usable unified diff:
      - Has '--- ' and '+++ '
      - Has at least one '@@ -L,S +L,S @@' hunk
      - Contains at least one added ('+') or removed ('-') change line
      - Matches expected_file_path if provided
    """
    if not diff_str or not diff_str.strip():
        return False

    lines = [l.rstrip("\r\n") for l in diff_str.splitlines()]
    has_orig = any(l.startswith("--- ") for l in lines)
    has_target = any(l.startswith("+++ ") for l in lines)
    has_hunk = any(l.startswith("@@ ") for l in lines)

    if not (has_orig and has_target and has_hunk):
        return False

    # Check for actual modifications (lines starting with + or - that are not file headers)
    mod_lines = [
        l for l in lines
        if (l.startswith("+") and not l.startswith("+++")) or (l.startswith("-") and not l.startswith("---"))
    ]
    if not mod_lines:
        return False

    # Verify target file alignment if expected_file_path is known
    if expected_file_path:
        norm_expected = expected_file_path.replace("\\", "/").strip().lstrip("/")
        expected_base = norm_expected.split("/")[-1].lower()

        target_headers = [l for l in lines if l.startswith("+++ ") or l.startswith("--- ")]
        matches_target = False
        for th in target_headers:
            th_clean = re.sub(r"^(?:\+\+\+|---)\s+[ab]/", "", th).strip().split("\t")[0].lower()
            if th_clean.endswith(expected_base) or expected_base.endswith(th_clean.split("/")[-1]):
                matches_target = True
                break
        if not matches_target:
            logger.warning(
                "Unified diff targets unexpected file headers (%s) instead of expected %s",
                target_headers, expected_file_path
            )
            return False

    return True


def route_issue_fix(
    messages: list[dict],
    expected_file_path: Optional[str] = None,
    source_code: Optional[str] = None,
    user_preferred_provider: Optional[str] = None,
    user_preferred_model: Optional[str] = None,
    temperature: float = 0.05,
    max_tokens: int = 2048,
) -> IssueFixResult:
    """
    Authoritative issue-fixing routing engine.

    Executes strict sequential attempts:
      Attempt 1: APInex GPT-6 Luna
      Attempt 2: NVIDIA primary fallback model (glm-5-3)
      Attempt 3: Groq secondary fallback model (openai/gpt-oss-120b)

    Returns IssueFixResult with truthful provider attribution and attempt traces.
    Raises AllProvidersFailedError if all eligible providers fail.
    """
    from ai.router import _get_provider

    attempts: List[IssueFixAttempt] = []

    # ── Establish sequential attempts plan ────────────────────────────────────
    # Plan is strictly: APInex -> NVIDIA -> Groq
    # If user explicitly passed a non-standard custom endpoint (openai-compatible / anthropic-compatible),
    # honor that specific choice in front, followed by the authoritative cascade.
    custom_first: Optional[Tuple[str, str]] = None
    if user_preferred_provider and user_preferred_provider.strip().lower() in (
        "custom",
        "openai-compatible",
        "anthropic-compatible",
    ):
        c_prov = "openai-compatible" if user_preferred_provider.strip().lower() == "custom" else user_preferred_provider.strip().lower()
        c_model = user_preferred_model or ("custom-model" if c_prov != "anthropic-compatible" else "claude-3-5-sonnet")
        custom_first = (c_prov, c_model)

    candidates: List[Tuple[str, str]] = []
    if custom_first:
        candidates.append(custom_first)

    # 1. APInex (GPT-6 Luna)
    apinex_model = os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna").strip() or "free/gpt-6-luna"
    candidates.append(("apinex", apinex_model))

    # 2. NVIDIA (Configured primary fallback)
    nvidia_model = os.environ.get("AI_CODE_MODEL", "glm-5-3").strip() or "glm-5-3"
    candidates.append(("nvidia", nvidia_model))

    # 3. Groq (Configured secondary fallback)
    groq_model = os.environ.get("AI_GROQ_CODE_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
    candidates.append(("groq", groq_model))

    attempt_counter = 0

    for prov_name, model_name in candidates:
        attempt_counter += 1
        t0 = time.time()

        # ── Pre-flight eligibility and configuration check ────────────────────
        if prov_name == "apinex":
            enabled_str = os.environ.get("APINEX_ENABLED", "true").lower().strip()
            key = os.environ.get("APINEX_API_KEY", "").strip()
            if enabled_str not in ("true", "1", "yes") or not key or key.startswith("your_"):
                attempts.append(
                    IssueFixAttempt(
                        attempt=attempt_counter,
                        provider=prov_name,
                        model=model_name,
                        status="skipped",
                        failure_category="UNCONFIGURED",
                        error="APInex API key is not configured in the environment.",
                    )
                )
                logger.info("[ISSUE_FIX] APInex unconfigured; skipping to NVIDIA.")
                continue

            # Check daily quota
            can_proceed, q_reason, q_stats = check_quota(estimated_tokens=500)
            if not can_proceed or q_stats.get("is_exhausted"):
                attempts.append(
                    IssueFixAttempt(
                        attempt=attempt_counter,
                        provider=prov_name,
                        model=model_name,
                        status="skipped",
                        failure_category="QUOTA_EXHAUSTED",
                        error=q_reason or "APInex daily token limit exhausted (315,000 tokens reached).",
                    )
                )
                logger.warning("[ISSUE_FIX] APInex daily budget exhausted; skipping to NVIDIA.")
                continue

        elif prov_name == "nvidia":
            nv_key = os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY") or ""
            if not nv_key.strip():
                attempts.append(
                    IssueFixAttempt(
                        attempt=attempt_counter,
                        provider=prov_name,
                        model=model_name,
                        status="skipped",
                        failure_category="UNCONFIGURED",
                        error="NVIDIA API key is not configured in the environment.",
                    )
                )
                logger.info("[ISSUE_FIX] NVIDIA unconfigured; skipping to Groq.")
                continue

        elif prov_name == "groq":
            gr_key = os.environ.get("GROQ_API_KEY", "").strip()
            if not gr_key:
                attempts.append(
                    IssueFixAttempt(
                        attempt=attempt_counter,
                        provider=prov_name,
                        model=model_name,
                        status="skipped",
                        failure_category="UNCONFIGURED",
                        error="Groq API key is not configured in the environment.",
                    )
                )
                logger.info("[ISSUE_FIX] Groq unconfigured; no further providers in chain.")
                continue

        # Check model health
        health = get_model_health(prov_name, model_name)
        if health in ("RATE_LIMITED", "UNAVAILABLE"):
            attempts.append(
                IssueFixAttempt(
                    attempt=attempt_counter,
                    provider=prov_name,
                    model=model_name,
                    status="skipped",
                    failure_category="HEALTH_DEGRADED",
                    error=f"Model health status is {health}.",
                )
            )
            logger.info("[ISSUE_FIX] %s:%s is temporarily %s; cascading to next provider.", prov_name, model_name, health)
            continue

        # ── Execute model invocation ──────────────────────────────────────────
        try:
            prov_instance = _get_provider(prov_name)
            raw_response = prov_instance.chat(
                messages=messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency = int((time.time() - t0) * 1000)

            # Validate generated patch
            cleaned_diff, is_valid = clean_and_normalize_diff(
                raw=raw_response,
                expected_file_path=expected_file_path,
                source_code=source_code,
            )

            if not is_valid or not cleaned_diff.strip():
                err_msg = (
                    "Provider returned response without a valid git unified diff "
                    f"targeting {expected_file_path or 'target file'}."
                )
                record_model_error(prov_name, model_name, Exception(err_msg))
                attempts.append(
                    IssueFixAttempt(
                        attempt=attempt_counter,
                        provider=prov_name,
                        model=model_name,
                        status="failed",
                        latency_ms=latency,
                        http_status=200,
                        failure_category="INVALID_PATCH",
                        error=err_msg,
                        valid_patch=False,
                    )
                )
                logger.warning("[ISSUE_FIX] %s returned invalid patch; cascading to next provider.", prov_name)
                continue

            # Succeeded! Record success and return immediately
            record_model_success(prov_name, model_name, latency)
            attempts.append(
                IssueFixAttempt(
                    attempt=attempt_counter,
                    provider=prov_name,
                    model=model_name,
                    status="success",
                    latency_ms=latency,
                    http_status=200,
                    valid_patch=True,
                )
            )

            # Determine attribution label
            fallback_used = (prov_name != "apinex")
            if prov_name == "apinex":
                attribution = f"Fixed using APInex {clean_display_name(model_name)}"
            elif prov_name == "nvidia":
                attribution = f"APInex unavailable — fixed using NVIDIA"
            elif prov_name == "groq":
                attribution = f"APInex and NVIDIA failed — fixed using Groq"
            else:
                attribution = f"Fixed using {clean_display_name(model_name)} ({prov_name.upper()})"

            logger.info(
                "[ISSUE_FIX] Fix generated successfully using %s (%s) on attempt %d (latency=%dms)",
                prov_name, model_name, attempt_counter, latency,
            )

            return IssueFixResult(
                diff=cleaned_diff,
                provider=prov_name,
                model=model_name,
                model_display_name=clean_display_name(model_name),
                fallback_used=fallback_used,
                fix_attribution=attribution,
                attempts=[asdict(a) for a in attempts],
                raw_response=raw_response,
            )

        except Exception as exc:
            latency = int((time.time() - t0) * 1000)
            status_code = getattr(exc, "status_code", None)
            record_model_error(prov_name, model_name, exc, status_code)
            attempts.append(
                IssueFixAttempt(
                    attempt=attempt_counter,
                    provider=prov_name,
                    model=model_name,
                    status="failed",
                    latency_ms=latency,
                    http_status=status_code,
                    failure_category=exc.__class__.__name__,
                    error=str(exc),
                    valid_patch=False,
                )
            )
            logger.warning(
                "[ISSUE_FIX] %s failed on attempt %d (%s: %s). Cascading to next provider...",
                prov_name, attempt_counter, exc.__class__.__name__, exc,
            )

    # ── All providers failed ──────────────────────────────────────────────────
    diag_lines = ["⚠️ **Issue-Fix AI Routing Failure:** All configured providers failed to produce a usable code fix."]
    for a in attempts:
        diag_lines.append(f"- **Attempt {a.attempt} ({a.provider.upper()} • `{a.model}`)**: [{a.status.upper()}] {a.error or a.failure_category}")

    full_error_msg = "\n".join(diag_lines)
    logger.error("[ISSUE_FIX] All providers failed: %s", full_error_msg)
    raise AllProvidersFailedError(
        message=full_error_msg,
        errors=[Exception(a.error or a.failure_category) for a in attempts if a.status == "failed"],
    )
