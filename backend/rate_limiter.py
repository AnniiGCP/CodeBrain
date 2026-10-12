"""
backend/rate_limiter.py
-----------------------
Rate limiting, concurrency management, and abuse protection:
  1. GitHub API Rate Limit Guard: queries GET /rate_limit before dispatching requests.
  2. Per-User Concurrency Cap: limits parallel auto-fix executions per user.
  3. Abuse Protection: caps connected repositories and hourly pipeline runs per user.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Repo

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# Configuration defaults
DEFAULT_MIN_GITHUB_RATE_LIMIT = 50
MAX_CONCURRENT_FIXES_PER_USER = 5
MAX_REPOS_PER_USER = 10
MAX_PIPELINE_RUNS_PER_HOUR = 20


# ── 1. GitHub API Rate Limit Guard ───────────────────────────────────────────

class GitHubRateLimitExceededError(RuntimeError):
    """Raised when the user's GitHub API quota has less than the safe threshold."""
    def __init__(self, remaining: int, limit: int, reset_epoch: int):
        self.remaining = remaining
        self.limit = limit
        self.reset_epoch = reset_epoch
        self.reset_datetime = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
        super().__init__(
            f"GitHub API rate limit is low ({remaining}/{limit} remaining). "
            f"Automation paused until quota resets at {self.reset_datetime.isoformat()}."
        )


@dataclass
class RateLimitInfo:
    remaining: int
    limit: int
    reset_epoch: int
    reset_datetime: datetime
    is_low: bool


def get_user_github_rate_limit(token: str | None) -> RateLimitInfo:
    """
    Query GitHub's GET /rate_limit endpoint.
    This call is free and does not consume any rate limit quota.
    """
    if not token or token.startswith("your_"):
        return RateLimitInfo(
            remaining=5000,
            limit=5000,
            reset_epoch=int(time.time()) + 3600,
            reset_datetime=datetime.fromtimestamp(int(time.time()) + 3600, tz=timezone.utc),
            is_low=False,
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{GITHUB_API_BASE}/rate_limit", headers=headers)
        if resp.is_success:
            data = resp.json()
            core = data.get("resources", {}).get("core", {})
            remaining = core.get("remaining", 5000)
            limit = core.get("limit", 5000)
            reset_epoch = core.get("reset", int(time.time()) + 3600)
            reset_dt = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
            return RateLimitInfo(
                remaining=remaining,
                limit=limit,
                reset_epoch=reset_epoch,
                reset_datetime=reset_dt,
                is_low=remaining < DEFAULT_MIN_GITHUB_RATE_LIMIT,
            )
    except Exception as exc:
        logger.warning("Could not query GitHub rate limit: %s", exc)

    # Default fallback if query fails
    return RateLimitInfo(
        remaining=5000,
        limit=5000,
        reset_epoch=int(time.time()) + 3600,
        reset_datetime=datetime.fromtimestamp(int(time.time()) + 3600, tz=timezone.utc),
        is_low=False,
    )


def ensure_github_rate_limit_available(token: str | None, min_remaining: int = DEFAULT_MIN_GITHUB_RATE_LIMIT) -> RateLimitInfo:
    """
    Check rate limit and raise GitHubRateLimitExceededError if below safe threshold.
    """
    info = get_user_github_rate_limit(token)
    if info.remaining < min_remaining:
        raise GitHubRateLimitExceededError(
            remaining=info.remaining,
            limit=info.limit,
            reset_epoch=info.reset_epoch,
        )
    return info


# ── 2. Per-User Concurrency Management ────────────────────────────────────────

_user_semaphores: dict[str, threading.Semaphore] = {}
_semaphore_lock = threading.Lock()


def get_user_fix_semaphore(user_id: str, max_concurrent: int = MAX_CONCURRENT_FIXES_PER_USER) -> threading.Semaphore:
    """Return a per-user Semaphore to limit parallel auto-fix operations."""
    with _semaphore_lock:
        if user_id not in _user_semaphores:
            _user_semaphores[user_id] = threading.Semaphore(max_concurrent)
        return _user_semaphores[user_id]


# ── 3. Abuse Protection & Quotas ──────────────────────────────────────────────

_user_pipeline_runs: dict[str, list[float]] = defaultdict(list)
_rate_track_lock = threading.Lock()


def check_user_repo_limit(user_id: str, db: Session, max_repos: int = MAX_REPOS_PER_USER) -> None:
    """Ensure a user cannot exceed the maximum number of connected repositories."""
    count = db.query(Repo).filter(Repo.user_id == user_id).count()
    if count >= max_repos:
        raise HTTPException(
            status_code=400,
            detail=f"Repository limit reached (maximum {max_repos} repositories per user). Please delete an existing repository to connect a new one.",
        )


def check_and_record_user_pipeline_run(user_id: str, max_runs_per_hour: int = MAX_PIPELINE_RUNS_PER_HOUR) -> None:
    """
    Sliding window rate limit for pipeline runs per hour per user.
    Raises HTTP 429 if the user exceeds the trigger limit.
    """
    now = time.time()
    one_hour_ago = now - 3600

    with _rate_track_lock:
        timestamps = _user_pipeline_runs[user_id]
        # Prune runs older than 1 hour
        timestamps = [t for t in timestamps if t > one_hour_ago]
        if len(timestamps) >= max_runs_per_hour:
            oldest = timestamps[0]
            retry_after_seconds = int(3600 - (now - oldest))
            raise HTTPException(
                status_code=429,
                detail=f"Pipeline trigger limit exceeded (maximum {max_runs_per_hour} runs per hour). Please wait {retry_after_seconds} seconds before triggering another run.",
                headers={"Retry-After": str(max(1, retry_after_seconds))},
            )
        timestamps.append(now)
        _user_pipeline_runs[user_id] = timestamps


# ── 4. Layered HTTP Rate Limiting & Abuse Prevention ─────────────────────────

from fastapi import Request
import os

# Configurable rate limits with safe defaults
AUTH_LOGIN_MAX_ATTEMPTS = int(os.getenv("AUTH_LOGIN_MAX_ATTEMPTS", "5"))
AUTH_LOGIN_WINDOW_SECONDS = int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "300"))  # 5 minutes
AUTH_REGISTER_MAX_HOURLY = int(os.getenv("AUTH_REGISTER_MAX_HOURLY", "15"))
AI_ACTIONS_MAX_PER_MINUTE = int(os.getenv("AI_ACTIONS_MAX_PER_MINUTE", "60"))
PUBLIC_MAX_PER_MINUTE = int(os.getenv("PUBLIC_MAX_PER_MINUTE", "180"))

_generic_rate_windows: dict[str, list[float]] = defaultdict(list)
_auth_failed_attempts: dict[str, list[float]] = defaultdict(list)


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address safely.
    Only trusts forwarding headers (X-Forwarded-For) if request arrives from a configured trusted proxy.
    Otherwise returns direct peer host to prevent header spoofing.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"
    trusted_proxies_env = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1").strip()
    trusted_proxies = {p.strip() for p in trusted_proxies_env.split(",") if p.strip()}

    if direct_ip in trusted_proxies or "*" in trusted_proxies:
        xfwd = request.headers.get("x-forwarded-for")
        if xfwd:
            # First IP in X-Forwarded-For is client origin
            parts = [p.strip() for p in xfwd.split(",") if p.strip()]
            if parts:
                return parts[0]
    return direct_ip


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    """
    Generic atomic sliding window rate limiter.
    Returns (allowed: bool, retry_after_seconds: int).
    """
    now = time.time()
    cutoff = now - window_seconds

    with _rate_track_lock:
        timestamps = _generic_rate_windows[key]
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= max_requests:
            oldest = timestamps[0]
            retry_after = int(window_seconds - (now - oldest))
            _generic_rate_windows[key] = timestamps
            return False, max(1, retry_after)
        timestamps.append(now)
        _generic_rate_windows[key] = timestamps
        return True, 0


def enforce_rate_limit(key: str, max_requests: int, window_seconds: int, detail: str) -> None:
    """Enforce rate limit or raise HTTP 429 Too Many Requests."""
    allowed, retry_after = check_rate_limit(key, max_requests, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"{detail} Please retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def check_login_rate_limit(request: Request, identifier: str) -> None:
    """
    Check login rate limit per IP and per normalized account identifier.
    Applies sliding window progressive delays and backoff for repeated failures.
    """
    ip = get_client_ip(request)
    now = time.time()
    cutoff = now - AUTH_LOGIN_WINDOW_SECONDS

    with _rate_track_lock:
        # Check IP failed attempts
        ip_failures = [t for t in _auth_failed_attempts[f"ip:{ip}"] if t > cutoff]
        _auth_failed_attempts[f"ip:{ip}"] = ip_failures
        if len(ip_failures) >= AUTH_LOGIN_MAX_ATTEMPTS * 3:
            oldest = ip_failures[0]
            retry_after = max(1, int(AUTH_LOGIN_WINDOW_SECONDS - (now - oldest)))
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts from this network. Please retry after {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

        # Check identifier failed attempts (normalized email/username)
        norm_id = identifier.strip().lower()
        id_failures = [t for t in _auth_failed_attempts[f"id:{norm_id}"] if t > cutoff]
        _auth_failed_attempts[f"id:{norm_id}"] = id_failures
        if len(id_failures) >= AUTH_LOGIN_MAX_ATTEMPTS:
            oldest = id_failures[0]
            retry_after = max(1, int(AUTH_LOGIN_WINDOW_SECONDS - (now - oldest)))
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts for this account. Please wait {retry_after} seconds before trying again.",
                headers={"Retry-After": str(retry_after)},
            )


def record_login_failure(request: Request, identifier: str) -> None:
    """Record an authentication failure timestamp for both client IP and identifier."""
    ip = get_client_ip(request)
    now = time.time()
    norm_id = identifier.strip().lower()

    with _rate_track_lock:
        _auth_failed_attempts[f"ip:{ip}"].append(now)
        _auth_failed_attempts[f"id:{norm_id}"].append(now)


def record_login_success(request: Request, identifier: str) -> None:
    """Clear failed attempt counters on successful authentication."""
    ip = get_client_ip(request)
    norm_id = identifier.strip().lower()

    with _rate_track_lock:
        _auth_failed_attempts.pop(f"ip:{ip}", None)
        _auth_failed_attempts.pop(f"id:{norm_id}", None)


def enforce_register_rate_limit(request: Request) -> None:
    """Rate limit account registration by client IP to prevent bot account creation."""
    ip = get_client_ip(request)
    enforce_rate_limit(
        key=f"register:ip:{ip}",
        max_requests=AUTH_REGISTER_MAX_HOURLY,
        window_seconds=3600,
        detail="Account registration rate limit reached.",
    )


def enforce_ai_action_rate_limit(user_id: str) -> None:
    """Rate limit expensive AI operations per authenticated user."""
    enforce_rate_limit(
        key=f"ai:user:{user_id}",
        max_requests=AI_ACTIONS_MAX_PER_MINUTE,
        window_seconds=60,
        detail="AI operation rate limit exceeded.",
    )


def enforce_public_rate_limit(request: Request) -> None:
    """Rate limit public endpoints per client IP."""
    ip = get_client_ip(request)
    enforce_rate_limit(
        key=f"public:ip:{ip}",
        max_requests=PUBLIC_MAX_PER_MINUTE,
        window_seconds=60,
        detail="API request rate limit exceeded.",
    )


def reset_rate_limit_tracking() -> None:
    """Helper for testing to reset in-memory counters."""
    with _rate_track_lock:
        _user_pipeline_runs.clear()
        _generic_rate_windows.clear()
        _auth_failed_attempts.clear()
    with _semaphore_lock:
        _user_semaphores.clear()

