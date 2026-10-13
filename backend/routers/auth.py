"""
routers/auth.py
---------------
Authentication endpoints:
  - GET  /me               — Return current authenticated user profile
  - POST /logout           — Clear session cookie
  - POST /auth/dev-login   — Development / test helper to create/log into a user
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import (
    GITHUB_OAUTH_AUTHORIZE_URL,
    GITHUB_OAUTH_TOKEN_URL,
    GITHUB_USER_API_URL,
    SESSION_COOKIE_NAME,
    create_session_token,
    get_current_user,
    get_optional_user,
    set_user_github_token,
    get_user_github_token,
    set_user_groq_token,
    set_user_nvidia_token,
    get_user_groq_token,
    get_user_nvidia_token,
    set_user_openrouter_token,
    get_user_openrouter_token,
    set_user_custom_ai_token,
    get_user_custom_ai_token,
    set_user_anthropic_token,
    get_user_anthropic_token,
    set_user_anthropic_compatible_token,
    get_user_anthropic_compatible_token,
    create_oauth_state,
    verify_oauth_state,
    hash_password,
    verify_password,
)

from database import get_db
from models import User
from rate_limiter import (
    check_login_rate_limit,
    record_login_failure,
    record_login_success,
    enforce_register_rate_limit,
    enforce_rate_limit,
    get_client_ip,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

GITHUB_OAUTH_SCOPES = "repo,workflow"


def _is_cookie_secure(request: Request | None = None) -> bool:
    """Determine if cookies should be marked Secure (HTTPS/production)."""
    if os.getenv("SECURE_COOKIES", "").lower() in ("true", "1", "yes"):
        return True
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        return True
    if request and hasattr(request, "url") and request.url.scheme == "https":
        return True
    return False


# ── Response / Request Models ─────────────────────────────────────────────────

class UserProfileResponse(BaseModel):
    id: str
    github_id: str
    github_username: str
    email: Optional[str] = None
    github_avatar_url: Optional[str] = None
    github_connected: bool = False
    created_at: str


class DevLoginRequest(BaseModel):
    github_id: str = Field(..., description="GitHub User ID (e.g. '123456')")
    github_username: str = Field(..., description="GitHub Username (e.g. 'octocat')")
    github_avatar_url: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email address")
    username: str = Field(..., min_length=2, max_length=50, description="Desired username")
    password: str = Field(..., min_length=8, description="Password (at least 8 characters)")


class PasswordLoginRequest(BaseModel):
    identifier: str = Field(..., description="Email address or username")
    password: str = Field(..., description="Account password")


class LoginResponse(BaseModel):
    user: UserProfileResponse
    token: str
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfileResponse, summary="Get current user profile")
def get_me(current_user: User = Depends(get_current_user)):
    """Return profile metadata for the authenticated user."""
    has_gh = bool(get_user_github_token(current_user))
    return UserProfileResponse(
        id=current_user.id,
        github_id=current_user.github_id,
        github_username=current_user.github_username,
        email=getattr(current_user, "user_email", None) or getattr(current_user, "email", None),
        github_avatar_url=current_user.github_avatar_url,
        github_connected=has_gh,
        created_at=current_user.created_at.isoformat() if current_user.created_at else "",
    )


@router.post("/auth/register", response_model=LoginResponse, summary="Register a new user account with email & password")
def register_user(
    body: RegisterRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Register a standard user account with email/username/password.
    Validates input format, enforces uniqueness, securely hashes password, and issues session cookie.
    Enforces IP-based rate limiting to prevent automated account creation.
    """
    import re
    import uuid

    # Rate limit registration attempts per IP
    enforce_register_rate_limit(request)

    clean_email = body.email.strip().lower()
    clean_username = body.username.strip()

    # Basic email validation
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a valid email address.",
        )

    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )

    # Check for existing user by email
    existing_email = db.query(User).filter(User.user_email == clean_email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # Check for existing user by username
    existing_user = db.query(User).filter(User.github_username == clean_username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already taken. Please choose another.",
        )

    # Create new standard user (never admin)
    user_id = str(uuid.uuid4())
    pw_hash = hash_password(body.password)
    new_user = User(
        id=user_id,
        github_id=f"usr_{uuid.uuid4().hex[:12]}",
        github_username=clean_username,
        user_email=clean_email,
        password_hash=pw_hash,
        github_avatar_url=None,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    try:
        token = create_session_token(new_user.id)
    except RuntimeError as r_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server configuration error: {r_err}. Please set a custom SESSION_SECRET in the Render dashboard environment variables.",
        )
    cookie_secure = _is_cookie_secure(request)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 30,
        samesite="none" if cookie_secure else "lax",
        secure=cookie_secure,
        path="/",
    )

    return LoginResponse(
        user=UserProfileResponse(
            id=new_user.id,
            github_id=new_user.github_id,
            github_username=new_user.github_username,
            email=new_user.user_email,
            github_avatar_url=new_user.github_avatar_url,
            github_connected=False,
            created_at=new_user.created_at.isoformat() if new_user.created_at else "",
        ),
        token=token,
        message="Account created successfully.",
    )


@router.post("/auth/login", response_model=LoginResponse, summary="Sign in with email/username and password")
def password_login(
    body: PasswordLoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Authenticate an existing user using their email address or username and password.
    Enforces per-IP and per-account failed attempt tracking with exponential backoff.
    """
    clean_identifier = body.identifier.strip()
    if not clean_identifier or not body.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identifier and password are required.",
        )

    # Check brute force / failed attempts rate limit
    check_login_rate_limit(request, clean_identifier)

    # Match by email or username
    user = (
        db.query(User)
        .filter(
            (User.user_email == clean_identifier.lower())
            | (User.github_username == clean_identifier)
        )
        .first()
    )

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        record_login_failure(request, clean_identifier)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password.",
        )

    # Successful authentication: clear failure count
    record_login_success(request, clean_identifier)

    try:
        token = create_session_token(user.id)
    except RuntimeError as r_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server configuration error: {r_err}. Please set a custom SESSION_SECRET in the Render dashboard environment variables.",
        )
    cookie_secure = _is_cookie_secure(request)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 30,
        samesite="none" if cookie_secure else "lax",
        secure=cookie_secure,
        path="/",
    )

    return LoginResponse(
        user=UserProfileResponse(
            id=user.id,
            github_id=user.github_id,
            github_username=user.github_username,
            email=user.user_email,
            github_avatar_url=user.github_avatar_url,
            github_connected=bool(get_user_github_token(user)),
            created_at=user.created_at.isoformat() if user.created_at else "",
        ),
        token=token,
        message="Signed in successfully.",
    )


@router.post("/logout", summary="Log out and clear session cookie")
def logout(response: Response, request: Request):
    """Clear session cookie to log out."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_cookie_secure(request),
    )
    return {"status": "logged_out", "message": "Successfully logged out."}


@router.post("/auth/dev-login", response_model=LoginResponse, summary="Dev / Test login endpoint")
def dev_login(
    body: DevLoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Development and testing endpoint to create or retrieve a User and issue a session token.
    Strictly blocked in production unless ALLOW_DEV_LOGIN=true is explicitly set.
    """
    env_mode = os.getenv("ENVIRONMENT", "development").lower()
    allow_dev = os.getenv("ALLOW_DEV_LOGIN", "false" if env_mode == "production" else "true").lower() in ("true", "1", "yes")
    if env_mode == "production" and not allow_dev:
        logger.warning("Blocked attempt to access /auth/dev-login in production mode from IP %s", get_client_ip(request))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development login bypass is disabled in production environments.",
        )

    # Moderate rate limit in dev
    enforce_rate_limit(f"dev_login:{get_client_ip(request)}", max_requests=30, window_seconds=60, detail="Dev login rate limit exceeded.")

    user = db.query(User).filter(User.github_id == body.github_id).first()
    if not user:
        user = User(
            github_id=body.github_id,
            github_username=body.github_username,
            github_avatar_url=body.github_avatar_url,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Update username/avatar if changed
        user.github_username = body.github_username
        if body.github_avatar_url:
            user.github_avatar_url = body.github_avatar_url
        db.commit()
        db.refresh(user)

    token = create_session_token(user.id)

    # Set httpOnly cookie with environment-aware security flag
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 30,
        samesite="lax",
        secure=_is_cookie_secure(request),
        path="/",
    )

    return LoginResponse(
        user=UserProfileResponse(
            id=user.id,
            github_id=user.github_id,
            github_username=user.github_username,
            github_avatar_url=user.github_avatar_url,
            created_at=user.created_at.isoformat() if user.created_at else "",
        ),
        token=token,
        message="Session created successfully.",
    )


# ── GitHub OAuth Endpoints ───────────────────────────────────────────────────

@router.get("/auth/github/login", summary="Initiate GitHub OAuth Login")
def github_login(
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
):
    """
    Redirect the browser to GitHub's OAuth authorization page.
    Requests scopes: 'repo,workflow'.
    """
    import os
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip()
    if not client_id or client_id.startswith("your_"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "GitHub OAuth is not configured. Please configure GITHUB_OAUTH_CLIENT_ID "
                "and GITHUB_OAUTH_CLIENT_SECRET in backend/.env from https://github.com/settings/developers"
            ),
        )

    callback_url = redirect_uri or os.environ.get(
        "GITHUB_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
    )

    try:
        oauth_state = state or create_oauth_state()
    except RuntimeError as r_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server configuration error: {r_err}. Please set a custom SESSION_SECRET in the Render dashboard environment variables.",
        )

    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": GITHUB_OAUTH_SCOPES,
        "state": oauth_state,
    }

    authorize_url = f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url=authorize_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/auth/github/callback", summary="GitHub OAuth Callback")
def github_callback(
    code: str = Query(..., description="Authorization code from GitHub"),
    state: Optional[str] = Query(None, description="CSRF state parameter"),
    db: Session = Depends(get_db),
):
    """
    Handle GitHub OAuth callback:
      1. Validate CSRF state signature.
      2. Exchange authorization code for GitHub access token.
      3. Fetch user profile from GitHub API (GET /user).
      4. Create or update User in DB.
      5. Encrypt and store the GitHub access token at rest.
      6. Establish session (sets httpOnly cookie).
      7. Redirect to frontend with session cookie.
    """
    import os

    # 1. CSRF State validation
    if state and not verify_oauth_state(state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state parameter (CSRF validation failed).",
        )

    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip()
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

    if not client_id or not client_secret or client_id.startswith("your_"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub OAuth credentials (CLIENT_ID / CLIENT_SECRET) are missing or set to placeholders.",
        )

    # 2. Exchange code for access token
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    redirect_uri = os.environ.get("GITHUB_OAUTH_REDIRECT_URI")
    if redirect_uri:
        token_payload["redirect_uri"] = redirect_uri

    headers = {"Accept": "application/json"}
    with httpx.Client(timeout=20) as client:
        token_resp = client.post(GITHUB_OAUTH_TOKEN_URL, json=token_payload, headers=headers)

    if not token_resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange GitHub authorization code: {token_resp.text}",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error_desc = token_data.get("error_description", token_data.get("error", "Unknown error"))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error_desc}",
        )

    # 3. Fetch user profile from GitHub API
    gh_headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20) as client:
        user_resp = client.get(GITHUB_USER_API_URL, headers=gh_headers)

    if not user_resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch GitHub user profile: {user_resp.text}",
        )

    user_info = user_resp.json()
    github_id = str(user_info["id"])
    github_username = user_info.get("login", f"user_{github_id}")
    github_avatar_url = user_info.get("avatar_url")

    # 4. Create or update User row in DB
    user = db.query(User).filter(User.github_id == github_id).first()
    if not user:
        user = User(
            github_id=github_id,
            github_username=github_username,
            github_avatar_url=github_avatar_url,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.github_username = github_username
        user.github_avatar_url = github_avatar_url

    # 5. Encrypt and store access token at rest
    set_user_github_token(user, access_token)
    db.commit()
    db.refresh(user)

    # 6. Establish session
    try:
        session_token = create_session_token(user.id)
    except RuntimeError as r_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server configuration error: {r_err}. Please set a custom SESSION_SECRET in the Render dashboard environment variables.",
        )

    # 7. Redirect to frontend with httpOnly session cookie and hash token for cross-domain auth
    cookie_secure = _is_cookie_secure()
    target_url = f"{frontend_url.rstrip('/')}/#session_token={session_token}"
    redirect_resp = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    redirect_resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        max_age=86400 * 30,
        samesite="none" if cookie_secure else "lax",
        secure=cookie_secure,
        path="/",
    )
    return redirect_resp


class GitHubRepoItem(BaseModel):
    id: int
    name: str
    full_name: str
    owner: str
    html_url: str
    clone_url: str
    description: Optional[str] = None
    private: bool
    default_branch: str
    language: Optional[str] = None
    updated_at: Optional[str] = None


class GitHubReposResponse(BaseModel):
    connected: bool
    repos: list[GitHubRepoItem]
    total: int
    username: Optional[str] = None


@router.get("/auth/github/repos", response_model=GitHubReposResponse, summary="List authenticated user repositories from GitHub")
def list_github_repositories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetch repository list directly from GitHub API for the connected account.
    Returns private and public repos the user has access to.
    """
    import os
    token = get_user_github_token(current_user)
    if not token:
        env_token = os.environ.get("GITHUB_TOKEN", "").strip()
        if env_token and not env_token.startswith("your_"):
            token = env_token

    if not token:
        return GitHubReposResponse(
            connected=False,
            repos=[],
            total=0,
            username=current_user.github_username,
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                "https://api.github.com/user/repos?per_page=50&sort=updated&affiliation=owner,collaborator,organization_member",
                headers=headers,
            )
    except Exception as exc:
        logger.error("GitHub API repos request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to communicate with GitHub API: {exc}")

    if resp.status_code == 401:
        set_user_github_token(current_user, "")
        db.commit()
        return GitHubReposResponse(
            connected=False,
            repos=[],
            total=0,
            username=current_user.github_username,
        )

    if not resp.is_success:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"GitHub API error fetching repositories: {resp.text}",
        )

    raw_items = resp.json()
    items: list[GitHubRepoItem] = []
    for r in raw_items:
        items.append(
            GitHubRepoItem(
                id=r.get("id", 0),
                name=r.get("name", ""),
                full_name=r.get("full_name", ""),
                owner=r.get("owner", {}).get("login", ""),
                html_url=r.get("html_url", ""),
                clone_url=r.get("clone_url", ""),
                description=r.get("description"),
                private=bool(r.get("private", False)),
                default_branch=r.get("default_branch", "main"),
                language=r.get("language"),
                updated_at=r.get("updated_at"),
            )
        )

    return GitHubReposResponse(
        connected=True,
        repos=items,
        total=len(items),
        username=current_user.github_username,
    )


@router.post("/auth/github/disconnect", summary="Disconnect GitHub account")
def disconnect_github(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect user GitHub account by clearing encrypted access token."""
    set_user_github_token(current_user, "")
    db.commit()
    db.refresh(current_user)
    return {"status": "disconnected", "message": "GitHub connection removed successfully."}


# ── User API Keys Management ──────────────────────────────────────────────────

class ApiKeyStatusResponse(BaseModel):
    has_nvidia_key: bool
    has_groq_key: bool
    has_custom_key: bool = False
    has_openai_compatible_key: bool = False
    custom_ai_base_url: Optional[str] = None
    custom_ai_model: Optional[str] = None
    custom_ai_display_name: Optional[str] = None
    openai_compatible_base_url: Optional[str] = None
    openai_compatible_model: Optional[str] = None
    openai_compatible_display_name: Optional[str] = None
    has_anthropic_compatible_key: bool = False
    anthropic_compatible_base_url: Optional[str] = None
    anthropic_compatible_model: Optional[str] = None
    anthropic_compatible_display_name: Optional[str] = None
    preferred_ai_provider: Optional[str] = None
    preferred_ai_model: Optional[str] = None
    # Deprecated fields retained as false for backward compatibility
    has_openrouter_key: bool = False
    has_anthropic_key: bool = False


class SaveApiKeysRequest(BaseModel):
    nvidia_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    custom_ai_api_key: Optional[str] = None
    custom_ai_base_url: Optional[str] = None
    custom_ai_model: Optional[str] = None
    custom_ai_display_name: Optional[str] = None
    openai_compatible_api_key: Optional[str] = None
    openai_compatible_base_url: Optional[str] = None
    openai_compatible_model: Optional[str] = None
    openai_compatible_display_name: Optional[str] = None
    anthropic_compatible_api_key: Optional[str] = None
    anthropic_compatible_base_url: Optional[str] = None
    anthropic_compatible_model: Optional[str] = None
    anthropic_compatible_display_name: Optional[str] = None
    preferred_ai_provider: Optional[str] = None
    preferred_ai_model: Optional[str] = None
    # Deprecated fields
    openrouter_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None


class TestConnectionRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class TestConnectionResponse(BaseModel):
    status: str
    provider: str
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    message: str


@router.get("/auth/keys", response_model=ApiKeyStatusResponse, summary="Check status of user API keys")
def get_api_key_status(current_user: User = Depends(get_current_user)):
    """Return status of configured custom AI providers and model preferences without exposing secrets."""
    has_custom = bool(get_user_custom_ai_token(current_user))
    custom_url = getattr(current_user, "custom_ai_base_url", None)
    custom_m = getattr(current_user, "custom_ai_model", None)
    custom_disp = getattr(current_user, "custom_ai_display_name", None)

    anth_url = getattr(current_user, "anthropic_compatible_base_url", None)
    anth_m = getattr(current_user, "anthropic_compatible_model", None)
    anth_disp = getattr(current_user, "anthropic_compatible_display_name", None)

    return ApiKeyStatusResponse(
        has_nvidia_key=bool(get_user_nvidia_token(current_user)),
        has_groq_key=bool(get_user_groq_token(current_user)),
        has_custom_key=has_custom,
        has_openai_compatible_key=has_custom,
        custom_ai_base_url=custom_url,
        custom_ai_model=custom_m,
        custom_ai_display_name=custom_disp,
        openai_compatible_base_url=custom_url,
        openai_compatible_model=custom_m,
        openai_compatible_display_name=custom_disp,
        has_anthropic_compatible_key=bool(get_user_anthropic_compatible_token(current_user)),
        anthropic_compatible_base_url=anth_url,
        anthropic_compatible_model=anth_m,
        anthropic_compatible_display_name=anth_disp,
        preferred_ai_provider=getattr(current_user, "preferred_ai_provider", None),
        preferred_ai_model=getattr(current_user, "preferred_ai_model", None),
        has_openrouter_key=False,
        has_anthropic_key=bool(get_user_anthropic_token(current_user) or get_user_anthropic_compatible_token(current_user)),
    )



def _validate_groq_key(key: str) -> None:
    """Make a minimal validation request to Groq API."""
    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=10.0,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Invalid Groq API key (Authentication Failed).")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Groq key validation test warning: %s", exc)


def _validate_nvidia_key(key: str) -> None:
    """Make a minimal validation request to NVIDIA NIM API with active model."""
    try:
        resp = httpx.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "meta/llama-3.2-11b-vision-instruct",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=10.0,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Invalid NVIDIA NIM API key (Authentication Failed).")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("NVIDIA key validation test warning: %s", exc)


def _validate_openrouter_key(key: str) -> None:
    """Make a minimal validation request to OpenRouter API."""
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://codebrain.dev",
                "X-Title": "CodeBrain AI System",
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=10.0,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Invalid OpenRouter API key (Authentication Failed).")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("OpenRouter key validation test warning: %s", exc)


def _validate_anthropic_key(key: str) -> None:
    """Make a minimal validation request to Anthropic Messages API."""
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=10.0,
        )
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Invalid Anthropic API key (Authentication Failed).")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Anthropic key validation test warning: %s", exc)


@router.post("/auth/keys/test", response_model=TestConnectionResponse, summary="Test AI provider connection")
def test_key_connection(
    body: TestConnectionRequest,
    current_user: User = Depends(get_current_user),
):
    """Test AI provider connection and return latency diagnostics without persisting secrets."""
    from ai.router import test_provider_connection
    p = body.provider.lower().strip()

    # Determine key to use (provided in body or saved in user profile)
    api_key = body.api_key
    if api_key is not None and not api_key.strip():
        p_name = {"nvidia": "NVIDIA", "groq": "Groq", "openai-compatible": "OpenAI-Compatible", "anthropic-compatible": "Anthropic-Compatible"}.get(p, p.upper())
        return TestConnectionResponse(
            status="error",
            provider=p,
            message=f"{p_name} API key not provided or configured.",
        )

    if not api_key:
        if p == "groq":
            api_key = get_user_groq_token(current_user)
        elif p in ("nvidia", "nim"):
            api_key = get_user_nvidia_token(current_user)
        elif p in ("custom", "openai-compatible"):
            api_key = get_user_custom_ai_token(current_user)
        elif p == "anthropic-compatible":
            api_key = get_user_anthropic_compatible_token(current_user)

    base_url = body.base_url or (
        getattr(current_user, "anthropic_compatible_base_url", None)
        if p == "anthropic-compatible"
        else getattr(current_user, "custom_ai_base_url", None)
    )
    model = body.model or getattr(current_user, "preferred_ai_model", None)

    res = test_provider_connection(
        provider=p,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return TestConnectionResponse(
        status=res.get("status", "error"),
        provider=p,
        model=res.get("model"),
        latency_ms=res.get("latency_ms"),
        message=res.get("message", "Test completed."),
    )


@router.post("/auth/keys", response_model=ApiKeyStatusResponse, summary="Save user AI provider keys & preferences")
def save_api_keys(
    body: SaveApiKeysRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate, encrypt and save AI provider keys, endpoints, and preferences."""
    if body.groq_api_key is not None:
        val = body.groq_api_key.strip()
        if val:
            _validate_groq_key(val)
            set_user_groq_token(current_user, val)
        else:
            set_user_groq_token(current_user, None)

    if body.nvidia_api_key is not None:
        val = body.nvidia_api_key.strip()
        if val:
            _validate_nvidia_key(val)
            set_user_nvidia_token(current_user, val)
        else:
            set_user_nvidia_token(current_user, None)

    if body.openrouter_api_key is not None:
        val = body.openrouter_api_key.strip()
        if val:
            _validate_openrouter_key(val)
            set_user_openrouter_token(current_user, val)
        else:
            set_user_openrouter_token(current_user, None)

    if body.anthropic_api_key is not None:
        val = body.anthropic_api_key.strip()
        if val:
            _validate_anthropic_key(val)
            set_user_anthropic_token(current_user, val)
        else:
            set_user_anthropic_token(current_user, None)

    # Handle OpenAI-Compatible (custom) keys and endpoint config
    custom_key_val = body.openai_compatible_api_key if body.openai_compatible_api_key is not None else body.custom_ai_api_key
    if custom_key_val is not None:
        val = custom_key_val.strip()
        if val:
            set_user_custom_ai_token(current_user, val)
        else:
            set_user_custom_ai_token(current_user, None)

    custom_url_val = body.openai_compatible_base_url if body.openai_compatible_base_url is not None else body.custom_ai_base_url
    if custom_url_val is not None:
        current_user.custom_ai_base_url = custom_url_val.strip() or None

    custom_model_val = body.openai_compatible_model if body.openai_compatible_model is not None else body.custom_ai_model
    if custom_model_val is not None:
        current_user.custom_ai_model = custom_model_val.strip() or None

    custom_disp_val = body.openai_compatible_display_name if body.openai_compatible_display_name is not None else body.custom_ai_display_name
    if custom_disp_val is not None:
        current_user.custom_ai_display_name = custom_disp_val.strip() or None

    # Handle Anthropic-Compatible keys and endpoint config
    if body.anthropic_compatible_api_key is not None:
        val = body.anthropic_compatible_api_key.strip()
        if val:
            set_user_anthropic_compatible_token(current_user, val)
        else:
            set_user_anthropic_compatible_token(current_user, None)

    if body.anthropic_compatible_base_url is not None:
        current_user.anthropic_compatible_base_url = body.anthropic_compatible_base_url.strip() or None

    if body.anthropic_compatible_model is not None:
        current_user.anthropic_compatible_model = body.anthropic_compatible_model.strip() or None

    if body.anthropic_compatible_display_name is not None:
        current_user.anthropic_compatible_display_name = body.anthropic_compatible_display_name.strip() or None

    if body.preferred_ai_provider is not None:
        p = body.preferred_ai_provider.strip().lower()
        if p in ("nvidia", "groq", "openai-compatible", "anthropic-compatible", "custom", ""):
            if p == "custom":
                p = "openai-compatible"
            current_user.preferred_ai_provider = p or "nvidia"

    if body.preferred_ai_model is not None:
        current_user.preferred_ai_model = body.preferred_ai_model.strip() or None

    db.commit()
    db.refresh(current_user)

    has_custom = bool(get_user_custom_ai_token(current_user))
    custom_url = getattr(current_user, "custom_ai_base_url", None)
    custom_m = getattr(current_user, "custom_ai_model", None)
    custom_disp = getattr(current_user, "custom_ai_display_name", None)

    anth_url = getattr(current_user, "anthropic_compatible_base_url", None)
    anth_m = getattr(current_user, "anthropic_compatible_model", None)
    anth_disp = getattr(current_user, "anthropic_compatible_display_name", None)

    return ApiKeyStatusResponse(
        has_nvidia_key=bool(get_user_nvidia_token(current_user)),
        has_groq_key=bool(get_user_groq_token(current_user)),
        has_custom_key=has_custom,
        has_openai_compatible_key=has_custom,
        custom_ai_base_url=custom_url,
        custom_ai_model=custom_m,
        custom_ai_display_name=custom_disp,
        openai_compatible_base_url=custom_url,
        openai_compatible_model=custom_m,
        openai_compatible_display_name=custom_disp,
        has_anthropic_compatible_key=bool(get_user_anthropic_compatible_token(current_user)),
        anthropic_compatible_base_url=anth_url,
        anthropic_compatible_model=anth_m,
        anthropic_compatible_display_name=anth_disp,
        preferred_ai_provider=getattr(current_user, "preferred_ai_provider", None),
        preferred_ai_model=getattr(current_user, "preferred_ai_model", None),
        has_openrouter_key=False,
        has_anthropic_key=False,
    )


@router.delete("/auth/keys/{provider}", summary="Delete custom API key")
def delete_api_key(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a custom user API key (reverting back to system/env fallback)."""
    p = provider.lower().strip()
    if p == "groq":
        set_user_groq_token(current_user, None)
    elif p in ("nvidia", "nim"):
        set_user_nvidia_token(current_user, None)
    elif p in ("custom", "openai-compatible"):
        set_user_custom_ai_token(current_user, None)
        current_user.custom_ai_base_url = None
        current_user.custom_ai_model = None
        current_user.custom_ai_display_name = None
    elif p == "anthropic-compatible":
        set_user_anthropic_compatible_token(current_user, None)
        current_user.anthropic_compatible_base_url = None
        current_user.anthropic_compatible_model = None
        current_user.anthropic_compatible_display_name = None
    elif p in ("openrouter", "anthropic"):
        # Legacy cleanup
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail="Unknown provider. Supported: 'nvidia', 'groq', 'openai-compatible', 'anthropic-compatible'."
        )

    db.commit()
    return {"status": "success", "message": f"{provider} configuration removed."}


# ── GET /ai/models (Unified Master AI Provider & Model Registry) ─────────────

@router.get("/ai/models", summary="Get Master AI Provider & Model Registry")
def get_ai_models_master(
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Returns the centralized AI Provider & Model registry.
    Includes verified display names, provider metadata, and availability statuses.
    OpenRouter is excluded from user-facing provider catalog.
    """
    from ai.registry import get_master_ai_registry
    return get_master_ai_registry(user=current_user)


# ── GET /ai/models/nvidia (NVIDIA Model Catalog & Selector) ───────────────────

@router.get("/ai/models/nvidia", summary="Get NVIDIA NIM model catalog with capability metadata")
def get_nvidia_model_catalog(
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Returns available NVIDIA NIM models with capability metadata and active statuses.
    Includes exact requested models: glm-5-3, glm-5-3-flash, deepseek-v4.1-flash, nemotron-3-ultra-550b-a55b.
    """
    from ai.registry import get_nvidia_models
    user_key = get_user_nvidia_token(current_user) if current_user else None
    models = get_nvidia_models(api_key=user_key)
    return {
        "provider": "nvidia",
        "total_models": len(models),
        "models": models,
    }


# ── GET /ai/model-for-task (Task-Specific Model Resolution) ───────────────────

@router.get("/ai/model-for-task", summary="Resolve Best Model & Fallback Chain for Task")
def get_model_for_task_endpoint(
    task: str = Query("CODEBASE_CHAT", description="Task identifier (e.g. DOCUMENTATION, CODE_FIX, CI_CD)"),
    context_size: int = Query(0, description="Estimated token count"),
    requires_vision: bool = Query(False, description="Whether visual multimodal input is required"),
    requires_tools: bool = Query(False, description="Whether tool calling is required"),
    complexity: str = Query("normal", description="Task complexity"),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Returns the authoritative routing decision for an AI task, including primary NVIDIA model,
    alternate NVIDIA model, Groq fallback, reason, and health status.
    """
    from ai.config import get_model_for_task
    pref_prov = current_user.preferred_ai_provider if current_user else None
    pref_model = current_user.preferred_ai_model if current_user else None
    return get_model_for_task(
        task=task,
        context_size=context_size,
        requires_vision=requires_vision,
        requires_tools=requires_tools,
        complexity=complexity,
        user_preferred_provider=pref_prov,
        user_preferred_model=pref_model,
    )


# ── GET /ai/apinex/quota (APInex Daily Token Quota Counter) ───────────────────

@router.get("/ai/apinex/quota", summary="Get APInex GPT-6 Luna Daily Token Quota Status")
@router.get("/ai/quota/apinex", summary="Get APInex GPT-6 Luna Daily Token Quota Status (alias)")
def get_apinex_quota_endpoint(
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Returns the server-authoritative daily token usage and quota status for APInex GPT-6 Luna.
    Tracks consumed tokens against the configurable daily application budget of 315,000 tokens.
    Never exposes API secrets.
    """
    from ai.quota_manager import get_usage
    return get_usage()


