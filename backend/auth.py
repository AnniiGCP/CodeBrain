"""
auth.py
-------
Authentication and multi-tenant data scoping module for CodeBrain.

Provides:
  - Cryptographic session token generation & verification (HMAC-SHA256).
  - get_current_user FastAPI dependency (supports httpOnly cookie and Authorization: Bearer header).
  - get_user_repo and get_user_symbol authorization helpers enforcing 403 Forbidden on tenant isolation breaches.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import Repo, Symbol, User

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session_token"
def _get_session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    env = os.environ.get("ENVIRONMENT", "development").lower()
    if env == "production":
        if not secret:
            raise RuntimeError("SESSION_SECRET must be set in production environment")
        if secret in ("codebrain-super-secret-session-key-2026", "your_random_session_secret"):
            raise RuntimeError("Default hardcoded SESSION_SECRET is not permitted in production")
    return secret or "dev-insecure-session-secret"
DEFAULT_EXPIRY_SECONDS = 86400 * 30  # 30 days

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API_URL = "https://api.github.com/user"


# ── Token Encryption / Decryption at Rest (Fernet) ───────────────────────────

def _get_fernet() -> Fernet:
    """Retrieve or derive a Fernet symmetric key from ENCRYPTION_KEY or SESSION_SECRET."""
    key_str = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not key_str or key_str.startswith("your_fernet_"):
        derived = hashlib.sha256(_get_session_secret().encode("utf-8")).digest()
        key_str = base64.urlsafe_b64encode(derived).decode("utf-8")
    else:
        try:
            Fernet(key_str.encode("utf-8"))
        except Exception:
            derived = hashlib.sha256(key_str.encode("utf-8")).digest()
            key_str = base64.urlsafe_b64encode(derived).decode("utf-8")
    return Fernet(key_str.encode("utf-8"))


def set_user_github_token(user: User, token: str) -> None:
    """Encrypt and store a user's GitHub access token on the User model."""
    if not token:
        user.encrypted_github_token = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.encode("utf-8"))
    user.encrypted_github_token = encrypted_bytes.decode("utf-8")


def get_user_github_token(user: User) -> str | None:
    """Decrypt and return a user's GitHub access token, or None if not set."""
    if not user.encrypted_github_token:
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_github_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt GitHub token for user %s: %s", user.id, exc)
        return None


import contextvars

# Context variables for user-provided API keys in current request context
current_user_groq_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_groq_key", default=None)
current_user_nvidia_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_nvidia_key", default=None)
current_user_openrouter_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_openrouter_key", default=None)
current_user_anthropic_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_anthropic_key", default=None)
current_user_custom_ai_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_custom_ai_key", default=None)
current_user_custom_ai_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_custom_ai_base_url", default=None)
current_user_custom_ai_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_custom_ai_model", default=None)
current_user_anthropic_compatible_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_anthropic_compatible_key", default=None)
current_user_anthropic_compatible_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_anthropic_compatible_base_url", default=None)
current_user_anthropic_compatible_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_anthropic_compatible_model", default=None)
current_user_preferred_provider: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_preferred_provider", default=None)
current_user_preferred_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_preferred_model", default=None)



def set_user_groq_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's Groq API key on the User model."""
    if not token or not token.strip():
        user.encrypted_groq_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_groq_api_key = encrypted_bytes.decode("utf-8")


def get_user_groq_token(user: User) -> str | None:
    """Decrypt and return a user's Groq API key, or None if not set."""
    if not getattr(user, "encrypted_groq_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_groq_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt Groq key for user %s: %s", user.id, exc)
        return None


def set_user_nvidia_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's NVIDIA NIM API key on the User model."""
    if not token or not token.strip():
        user.encrypted_nvidia_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_nvidia_api_key = encrypted_bytes.decode("utf-8")


def get_user_nvidia_token(user: User) -> str | None:
    """Decrypt and return a user's NVIDIA NIM API key, or None if not set."""
    if not getattr(user, "encrypted_nvidia_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_nvidia_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt NVIDIA key for user %s: %s", user.id, exc)
        return None


def set_user_openrouter_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's OpenRouter API key on the User model."""
    if not token or not token.strip():
        user.encrypted_openrouter_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_openrouter_api_key = encrypted_bytes.decode("utf-8")


def get_user_openrouter_token(user: User) -> str | None:
    """Decrypt and return a user's OpenRouter API key, or None if not set."""
    if not getattr(user, "encrypted_openrouter_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_openrouter_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt OpenRouter key for user %s: %s", user.id, exc)
        return None


def set_user_custom_ai_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's Custom AI endpoint API key on the User model."""
    if not token or not token.strip():
        user.encrypted_custom_ai_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_custom_ai_api_key = encrypted_bytes.decode("utf-8")


def get_user_custom_ai_token(user: User) -> str | None:
    """Decrypt and return a user's Custom AI endpoint API key, or None if not set."""
    if not getattr(user, "encrypted_custom_ai_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_custom_ai_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt Custom AI key for user %s: %s", user.id, exc)
        return None


def set_user_anthropic_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's Anthropic API key on the User model."""
    if not token or not token.strip():
        user.encrypted_anthropic_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_anthropic_api_key = encrypted_bytes.decode("utf-8")


def get_user_anthropic_token(user: User) -> str | None:
    """Decrypt and return a user's Anthropic API key, or None if not set."""
    if not getattr(user, "encrypted_anthropic_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_anthropic_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt Anthropic key for user %s: %s", user.id, exc)
        return None


def set_user_anthropic_compatible_token(user: User, token: str | None) -> None:
    """Encrypt and store a user's Anthropic-Compatible API key on the User model."""
    if not token or not token.strip():
        user.encrypted_anthropic_compatible_api_key = None
        return
    f = _get_fernet()
    encrypted_bytes = f.encrypt(token.strip().encode("utf-8"))
    user.encrypted_anthropic_compatible_api_key = encrypted_bytes.decode("utf-8")


def get_user_anthropic_compatible_token(user: User) -> str | None:
    """Decrypt and return a user's Anthropic-Compatible API key, or None if not set."""
    if not getattr(user, "encrypted_anthropic_compatible_api_key", None):
        return None
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(user.encrypted_anthropic_compatible_api_key.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt Anthropic-Compatible key for user %s: %s", user.id, exc)
        return None


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def hash_password(password: str) -> str:
    """Hash password securely using PBKDF2-HMAC-SHA256 with random salt."""
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"


def verify_password(password: str, hashed: str | None) -> bool:
    """Verify a plaintext password against a stored salt$hash string."""
    if not hashed or "$" not in hashed:
        return False
    try:
        salt, expected_hex = hashed.split("$", 1)
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
        return hmac.compare_digest(expected_hex, computed_key)
    except Exception:
        return False


def create_session_token(user_id: str, expires_in_seconds: int = DEFAULT_EXPIRY_SECONDS) -> str:
    """Create a signed, tamper-proof session token with expiry timestamp."""
    exp = int(time.time()) + expires_in_seconds
    payload = {"uid": user_id, "exp": exp}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)

    signature = hmac.new(
        _get_session_secret().encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64_encode(signature)

    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str) -> str | None:
    """
    Verify signature and expiration of a session token.
    Returns user_id if valid, or None if invalid/expired.
    """
    if not token or "." not in token:
        return None

    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(
            _get_session_secret().encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        provided_sig = _b64_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            logger.warning("Session token HMAC verification failed.")
            return None

        payload_bytes = _b64_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        if int(payload.get("exp", 0)) < int(time.time()):
            logger.info("Session token has expired.")
            return None

        return str(payload.get("uid"))
    except Exception as exc:
        logger.warning("Error parsing session token: %s", exc)
        return None


# ── Current User Dependency ───────────────────────────────────────────────────

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that extracts the authenticated user.
    Checks:
      1. Cookie 'session_token'
      2. Header 'Authorization: Bearer <token>'
    Raises HTTP 401 Unauthorized if missing, expired, or invalid.
    """
    token: str | None = request.cookies.get(SESSION_COOKIE_NAME)

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = verify_session_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with this session no longer exists.",
        )

    # Set user-provided API keys in request context
    groq_k = get_user_groq_token(user)
    if groq_k:
        current_user_groq_key.set(groq_k)
    nvidia_k = get_user_nvidia_token(user)
    if nvidia_k:
        current_user_nvidia_key.set(nvidia_k)
    openrouter_k = get_user_openrouter_token(user)
    if openrouter_k:
        current_user_openrouter_key.set(openrouter_k)
    anthropic_k = get_user_anthropic_token(user)
    if anthropic_k:
        current_user_anthropic_key.set(anthropic_k)
    custom_k = get_user_custom_ai_token(user)
    if custom_k:
        current_user_custom_ai_key.set(custom_k)
    if getattr(user, "custom_ai_base_url", None):
        current_user_custom_ai_base_url.set(user.custom_ai_base_url)
    if getattr(user, "custom_ai_model", None):
        current_user_custom_ai_model.set(user.custom_ai_model)
    anthropic_compat_k = get_user_anthropic_compatible_token(user)
    if anthropic_compat_k:
        current_user_anthropic_compatible_key.set(anthropic_compat_k)
    if getattr(user, "anthropic_compatible_base_url", None):
        current_user_anthropic_compatible_base_url.set(user.anthropic_compatible_base_url)
    if getattr(user, "anthropic_compatible_model", None):
        current_user_anthropic_compatible_model.set(user.anthropic_compatible_model)
    if getattr(user, "preferred_ai_provider", None):
        current_user_preferred_provider.set(user.preferred_ai_provider)
    if getattr(user, "preferred_ai_model", None):
        current_user_preferred_model.set(user.preferred_ai_model)

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    FastAPI dependency that extracts the authenticated user if session exists,
    or returns None without raising HTTP 401.
    """
    token: str | None = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :].strip()

    if not token:
        return None

    user_id = verify_session_token(token)
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    # Set user-provided API keys in request context
    groq_k = get_user_groq_token(user)
    if groq_k:
        current_user_groq_key.set(groq_k)
    nvidia_k = get_user_nvidia_token(user)
    if nvidia_k:
        current_user_nvidia_key.set(nvidia_k)
    anthropic_k = get_user_anthropic_token(user)
    if anthropic_k:
        current_user_anthropic_key.set(anthropic_k)
    custom_k = get_user_custom_ai_token(user)
    if custom_k:
        current_user_custom_ai_key.set(custom_k)
    if getattr(user, "custom_ai_base_url", None):
        current_user_custom_ai_base_url.set(user.custom_ai_base_url)
    if getattr(user, "custom_ai_model", None):
        current_user_custom_ai_model.set(user.custom_ai_model)
    anthropic_compat_k = get_user_anthropic_compatible_token(user)
    if anthropic_compat_k:
        current_user_anthropic_compatible_key.set(anthropic_compat_k)
    if getattr(user, "anthropic_compatible_base_url", None):
        current_user_anthropic_compatible_base_url.set(user.anthropic_compatible_base_url)
    if getattr(user, "anthropic_compatible_model", None):
        current_user_anthropic_compatible_model.set(user.anthropic_compatible_model)
    if getattr(user, "preferred_ai_provider", None):
        current_user_preferred_provider.set(user.preferred_ai_provider)
    if getattr(user, "preferred_ai_model", None):
        current_user_preferred_model.set(user.preferred_ai_model)

    return user


# ── Data Scoping & Authorization Helpers ──────────────────────────────────────

def get_user_repo(
    repo_id: str,
    db: Session,
    current_user: User,
) -> Repo:
    """
    Look up a repository by repo_id and verify ownership by current_user.
    Raises:
      - HTTP 404 if repo does not exist.
      - HTTP 403 if repo belongs to a different user.
    """
    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found.")

    if repo.user_id != current_user.id:
        logger.warning(
            "Access denied: User %s (%s) attempted to access Repo %s owned by User %s",
            current_user.id,
            current_user.github_username,
            repo_id,
            repo.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this repository.",
        )

    return repo


def get_user_symbol(
    symbol_id: int,
    db: Session,
    current_user: User,
) -> Symbol:
    """
    Look up a code Symbol by symbol_id and verify that its parent repository
    belongs to current_user.
    Raises:
      - HTTP 404 if symbol does not exist.
      - HTTP 403 if parent repo belongs to a different user.
    """
    symbol = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not symbol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found.")

    repo = db.query(Repo).filter(Repo.id == symbol.repo_id).first()
    if not repo or repo.user_id != current_user.id:
        logger.warning(
            "Access denied: User %s attempted to access Symbol %d belonging to Repo %s",
            current_user.id,
            symbol_id,
            symbol.repo_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own the repository containing this symbol.",
        )

    return symbol


def create_oauth_state() -> str:
    """Create a tamper-proof state string containing timestamp and HMAC signature."""
    payload = f"state_{int(time.time())}_{os.urandom(8).hex()}"
    sig = hmac.new(_get_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_oauth_state(state: str, max_age_seconds: int = 600) -> bool:
    """Verify tamper-proof state signature and freshness (default 10 min window)."""
    if not state or "." not in state:
        return False
    try:
        payload, sig = state.split(".", 1)
        expected_sig = hmac.new(_get_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return False
        parts = payload.split("_")
        if len(parts) >= 2:
            ts = int(parts[1])
            if time.time() - ts > max_age_seconds:
                return False
        return True
    except Exception:
        return False
