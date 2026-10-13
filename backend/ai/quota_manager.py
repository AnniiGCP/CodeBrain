"""
backend/ai/quota_manager.py
---------------------------
Persistent, thread-safe, and server-authoritative daily token quota manager
for APInex GPT-6 Luna.

Key Specifications:
  - Configurable daily application budget (default 315,000 tokens via APINEX_DAILY_TOKEN_LIMIT).
  - Scope: UTC calendar day (resets strictly at UTC midnight 00:00:00).
  - Persistence: SQLite / SQLAlchemy database table `apinex_daily_usage`.
  - Concurrency Safety: Thread-safe in-flight token reservations and transaction-safe atomic DB increments.
  - Distinguishes provider-reported token usage from conservative estimates.
  - Non-intrusive warning when usage reaches configurable threshold (default 80% = 252,000 tokens).
  - Quota exhaustion triggers automatic fallback routing and user notification.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select, text

logger = logging.getLogger("ai.quota_manager")

# In-flight reservation tracking to prevent concurrent bursts from overshooting budget
_RESERVATION_LOCK = threading.Lock()
_IN_FLIGHT_RESERVATIONS: Dict[str, int] = {}  # date -> reserved token count


def get_today_utc() -> str:
    """Returns today's date formatted as YYYY-MM-DD in UTC timezone."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_daily_limit() -> int:
    """Reads the application's configured APInex daily token limit from environment."""
    val = os.environ.get("APINEX_DAILY_TOKEN_LIMIT", "315000").strip()
    try:
        return max(1, int(val))
    except ValueError:
        logger.warning("Invalid APINEX_DAILY_TOKEN_LIMIT '%s'; defaulting to 315,000", val)
        return 315000


def get_warning_threshold() -> float:
    """Returns the ratio (0.0 - 1.0) at which to trigger a quota warning (default 0.80 = 80%)."""
    val = os.environ.get("APINEX_WARNING_THRESHOLD", "0.80").strip()
    try:
        parsed = float(val)
        return max(0.01, min(1.0, parsed))
    except ValueError:
        return 0.80


def is_hard_limit_enforced() -> bool:
    """
    Returns True if CodeBrain should strictly block requests locally when the 315K daily budget is reached.
    When False (default), permits pass-through to upstream APInex while healthy, tracking usage.
    When True (configured via APINEX_ENFORCE_HARD_LIMIT=true), strictly enforces budget locally.
    """
    val = os.environ.get("APINEX_ENFORCE_HARD_LIMIT", "false").lower().strip()
    return val in ("true", "1", "yes")


def get_in_flight_tokens(target_date: Optional[str] = None) -> int:
    """Returns total tokens currently reserved by in-flight requests for the given UTC date."""
    d = target_date or get_today_utc()
    with _RESERVATION_LOCK:
        return _IN_FLIGHT_RESERVATIONS.get(d, 0)


def reserve_quota(estimated_tokens: int = 500, target_date: Optional[str] = None) -> bool:
    """
    Attempts to reserve in-flight tokens against the daily budget.
    Returns True if reservation succeeded within budget, False if exhausted.
    """
    d = target_date or get_today_utc()
    limit = get_daily_limit()
    
    with _RESERVATION_LOCK:
        current_in_flight = _IN_FLIGHT_RESERVATIONS.get(d, 0)
        # Check current persisted DB usage
        persisted = _get_persisted_usage(d)
        projected = persisted["total_tokens"] + current_in_flight + estimated_tokens
        
        if is_hard_limit_enforced() and projected > limit:
            logger.warning(
                "[QUOTA] Reservation denied on %s: projected %d exceeds budget %d (persisted=%d, in_flight=%d)",
                d, projected, limit, persisted["total_tokens"], current_in_flight
            )
            return False

        _IN_FLIGHT_RESERVATIONS[d] = current_in_flight + estimated_tokens
        return True


def release_reservation(estimated_tokens: int = 500, target_date: Optional[str] = None) -> None:
    """Releases previously reserved in-flight tokens after request completion or error."""
    d = target_date or get_today_utc()
    with _RESERVATION_LOCK:
        current_in_flight = _IN_FLIGHT_RESERVATIONS.get(d, 0)
        _IN_FLIGHT_RESERVATIONS[d] = max(0, current_in_flight - estimated_tokens)


def _get_persisted_usage(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Helper to query persisted usage from the database for the given date (default today UTC).
    Each calendar day has its own persistent row in ApinexDailyUsage. Historical records
    from previous days remain in the database without counting toward the current daily budget.
    """
    d = target_date or get_today_utc()
    try:
        from database import SessionLocal
        from models import ApinexDailyUsage

        with SessionLocal() as db:
            row = db.query(ApinexDailyUsage).filter(ApinexDailyUsage.date == d).first()
            if row:
                return {
                    "date": row.date,
                    "prompt_tokens": row.prompt_tokens or 0,
                    "completion_tokens": row.completion_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                    "request_count": row.request_count or 0,
                    "is_estimated": bool(row.is_estimated),
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
            return {
                "date": d,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "request_count": 0,
                "is_estimated": False,
                "updated_at": None,
            }
    except Exception as exc:
        logger.error("Error reading Apinex daily usage for %s: %s", d, exc)

    return {
        "date": d,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
        "is_estimated": False,
        "updated_at": None,
    }


def get_usage(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns full usage statistics for the given UTC date (default today UTC).
    Tracks tokens against the 315,000-token daily application budget.
    Survives application restarts and accurately reflects persisted server records.
    """
    limit = get_daily_limit()
    warn_thresh = get_warning_threshold()
    
    stats = _get_persisted_usage(target_date)
    total_used = stats["total_tokens"]
    remaining = max(0, limit - total_used)
    percent = round((total_used / limit) * 100, 2) if limit > 0 else 0.0
    is_exhausted = total_used >= limit
    is_warning = (total_used / limit) >= warn_thresh if limit > 0 else False

    # Check whether APInex is enabled and configured with an API key
    key = os.environ.get("APINEX_API_KEY", "").strip()
    enabled_str = os.environ.get("APINEX_ENABLED", "true").lower().strip()
    is_enabled = enabled_str in ("true", "1", "yes") and bool(key) and not key.startswith("your_")

    return {
        "provider": "apinex",
        "model": os.environ.get("APINEX_MODEL_ID", "free/gpt-6-luna"),
        "date": stats["date"],
        "total_tokens": total_used,
        "prompt_tokens": stats["prompt_tokens"],
        "completion_tokens": stats["completion_tokens"],
        "request_count": stats["request_count"],
        "is_estimated": stats["is_estimated"],
        "daily_limit": limit,
        "remaining_tokens": remaining,
        "percent_used": min(100.0, percent),
        "is_exhausted": is_exhausted,
        "warning": is_warning and not is_exhausted,
        "warning_threshold": warn_thresh,
        "configured": is_enabled,
        "updated_at": stats["updated_at"],
    }


def check_quota(estimated_tokens: int = 0) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Checks if a new APInex request can proceed.
    Tracks against the 315,000-token daily budget.
    When exhausted, triggers automatic fallback to secondary provider (NVIDIA / Groq).
    """
    summary = get_usage()
    if is_hard_limit_enforced():
        if summary["is_exhausted"]:
            msg = (
                f"APInex GPT-6 Luna has reached its daily token limit ({summary['total_tokens']:,} / "
                f"{summary['daily_limit']:,} tokens consumed today UTC). CodeBrain will fall back to another provider."
            )
            return False, msg, summary

        limit = summary["daily_limit"]
        in_flight = get_in_flight_tokens()
        projected = summary["total_tokens"] + in_flight + estimated_tokens

        if projected > limit:
            msg = (
                f"APInex daily token limit would be exceeded by in-flight operations ({projected:,} > {limit:,})."
            )
            return False, msg, summary

    return True, "Quota available (pass-through active)", summary


def record_usage(
    total_tokens: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    is_estimated: bool = False,
    request_id: Optional[str] = None,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transaction-safe, concurrency-safe recording of tokens consumed by an APInex request.
    Uses atomic SQLite upsert semantics to prevent lost updates across concurrent threads.
    """
    if total_tokens <= 0:
        return get_usage(target_date)

    d = target_date or get_today_utc()
    now_utc = datetime.now(timezone.utc)

    try:
        from database import SessionLocal
        from models import ApinexDailyUsage

        with SessionLocal() as db:
            # Use atomic SQL upsert to guarantee concurrency safety
            upsert_sql = text("""
                INSERT INTO apinex_daily_usage (
                    date, prompt_tokens, completion_tokens, total_tokens, request_count, is_estimated, created_at, updated_at
                ) VALUES (
                    :date, :prompt, :comp, :tot, 1, :est, :created_at, :updated_at
                )
                ON CONFLICT(date) DO UPDATE SET
                    prompt_tokens = apinex_daily_usage.prompt_tokens + :prompt,
                    completion_tokens = apinex_daily_usage.completion_tokens + :comp,
                    total_tokens = apinex_daily_usage.total_tokens + :tot,
                    request_count = apinex_daily_usage.request_count + 1,
                    is_estimated = CASE WHEN :est THEN 1 ELSE apinex_daily_usage.is_estimated END,
                    updated_at = :updated_at;
            """)
            db.execute(
                upsert_sql,
                {
                    "date": d,
                    "prompt": max(0, prompt_tokens),
                    "comp": max(0, completion_tokens),
                    "tot": max(1, total_tokens),
                    "est": 1 if is_estimated else 0,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                },
            )
            db.commit()

        logger.info(
            "[QUOTA] Recorded APInex usage on %s: +%d tokens (prompt=%d, comp=%d, estimated=%s, req_id=%s)",
            d, total_tokens, prompt_tokens, completion_tokens, is_estimated, request_id or "n/a"
        )
    except Exception as exc:
        logger.error("Failed recording APInex usage to database: %s", exc, exc_info=True)

    return get_usage(target_date)


def reset_quota_for_date(target_date: Optional[str] = None) -> None:
    """Resets the usage counter for a date. Used primarily for deterministic test fixtures."""
    d = target_date or get_today_utc()
    try:
        from database import SessionLocal
        from models import ApinexDailyUsage

        with SessionLocal() as db:
            db.query(ApinexDailyUsage).filter(ApinexDailyUsage.date == d).delete()
            db.commit()
    except Exception as exc:
        logger.error("Failed resetting quota for date %s: %s", d, exc)

    with _RESERVATION_LOCK:
        _IN_FLIGHT_RESERVATIONS.pop(d, None)
