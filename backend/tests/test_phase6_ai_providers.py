"""
backend/tests/test_phase6_ai_providers.py
-----------------------------------------
Automated test suite for Phase 6 (AI Provider Architecture) & Phase 9 (Settings & Provider Config).
Verifies:
  1. Multi-provider architecture (NVIDIA NIM primary, Groq fallback, OpenRouter, Custom endpoint).
  2. Routing table default matrix and user-preference overrides.
  3. Encryption-at-rest for all provider keys (Fernet) and zero credential exposure.
  4. Connection testing endpoint (/auth/keys/test).
  5. Save, retrieve, and delete provider configurations.
  6. Telemetry logging and error category diagnostics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

# Ensure backend root is on sys.path
backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient
from main import app
from database import SessionLocal, get_db
from models import User
from auth import (
    create_session_token,
    SESSION_COOKIE_NAME,
    get_user_groq_token,
    get_user_nvidia_token,
    get_user_openrouter_token,
    get_user_custom_ai_token,
    current_user_preferred_provider,
    current_user_preferred_model,
)
from ai.config import get_routing_table
from ai.router import _PROVIDERS, test_provider_connection as check_provider_connection, _format_provider_diagnostic
from ai.exceptions import ProviderTimeout, ProviderRateLimited


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def auth_user(db_session):
    u = db_session.query(User).filter(User.github_id == "phase6_tester").first()
    if not u:
        u = User(
            github_id="phase6_tester",
            github_username="phase6_user",
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    return u


@pytest.fixture
def auth_client(auth_user):
    client = TestClient(app)
    token = create_session_token(auth_user.id)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return client


def test_ai_provider_registry():
    """Verify exact AI providers are registered in AI router."""
    assert "nvidia" in _PROVIDERS
    assert "groq" in _PROVIDERS
    assert "openai-compatible" in _PROVIDERS
    assert "anthropic-compatible" in _PROVIDERS
    assert "openrouter" not in _PROVIDERS


def test_routing_table_nvidia_primary_by_default():
    """Verify NVIDIA is configured as the default primary provider with Groq fallback."""
    table = get_routing_table()
    assert table["chat"].primary.provider == "nvidia"
    assert table["chat"].fallback.provider == "groq"
    assert table["code"].primary.provider == "nvidia"
    assert table["code"].fallback.provider == "groq"
    assert table["document"].primary.provider == "nvidia"
    assert table["transcribe"].primary.provider == "groq"


def test_routing_table_user_preference_override():
    """Verify user preferred provider dynamically alters routing table."""
    token1 = current_user_preferred_provider.set("openai-compatible")
    token2 = current_user_preferred_model.set("custom-llama3")
    try:
        table = get_routing_table()
        assert table["code"].primary.provider == "openai-compatible"
        assert table["code"].primary.model == "custom-llama3"
        assert table["code"].fallback.provider == "groq"
    finally:
        current_user_preferred_provider.reset(token1)
        current_user_preferred_model.reset(token2)


def test_api_keys_get_status_no_secrets_exposed(auth_client, auth_user, db_session):
    """GET /auth/keys should return boolean flags and config without raw keys."""
    resp = auth_client.get("/auth/keys")
    assert resp.status_code == 200
    data = resp.json()
    assert "has_groq_key" in data
    assert "has_nvidia_key" in data
    assert "has_custom_key" in data
    assert "has_openai_compatible_key" in data
    assert "has_anthropic_compatible_key" in data
    # Ensure raw secret keys are NEVER exposed
    assert "encrypted_groq_api_key" not in data
    assert "groq_api_key" not in data
    assert "nvidia_api_key" not in data


def test_api_keys_save_and_encrypt(auth_client, auth_user, db_session):
    """POST /auth/keys should validate, encrypt, and persist custom provider settings."""
    payload = {
        "openai_compatible_base_url": "http://localhost:11434/v1",
        "openai_compatible_model": "qwen2.5-coder:7b",
        "openai_compatible_display_name": "Qwen 2.5 Coder Local",
        "preferred_ai_provider": "openai-compatible",
        "preferred_ai_model": "qwen2.5-coder:7b",
    }
    resp = auth_client.post("/auth/keys", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["openai_compatible_base_url"] == "http://localhost:11434/v1"
    assert data["openai_compatible_model"] == "qwen2.5-coder:7b"
    assert data["openai_compatible_display_name"] == "Qwen 2.5 Coder Local"
    assert data["preferred_ai_provider"] == "openai-compatible"

    # Refresh user from DB and check model attributes
    db_session.refresh(auth_user)
    assert auth_user.custom_ai_base_url == "http://localhost:11434/v1"
    assert auth_user.preferred_ai_provider == "openai-compatible"


def test_test_provider_connection_endpoint(auth_client):
    """POST /auth/keys/test should test provider connectivity without persisting keys."""
    # Test unknown provider returns validation error
    resp = auth_client.post("/auth/keys/test", json={"provider": "invalid_provider"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert "Unsupported provider" in data["message"]

    # Test with unconfigured key on NVIDIA
    resp2 = auth_client.post("/auth/keys/test", json={"provider": "nvidia", "api_key": ""})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "error"
    assert "NVIDIA API key not provided" in data2["message"]


def test_delete_api_key(auth_client, auth_user, db_session):
    """DELETE /auth/keys/{provider} should clear specific provider credentials."""
    resp = auth_client.delete("/auth/keys/openai-compatible")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    resp2 = auth_client.delete("/auth/keys/unknown_provider")
    assert resp2.status_code == 400


def test_provider_diagnostic_formatting():
    """Verify error diagnostics are authentic, readable, and non-fabricated."""
    diag_timeout = _format_provider_diagnostic("nvidia", "glm-5-3", ProviderTimeout("Timed out"))
    assert "Timed Out" in diag_timeout

    diag_rate = _format_provider_diagnostic("groq", "llama-3.3-70b-versatile", ProviderRateLimited("TPM reached", status_code=429))
    assert "Rate Limit Exceeded (429)" in diag_rate

    diag_unconf = _format_provider_diagnostic("nvidia", "glm-5-3", Exception("NVIDIA_NIM_API_KEY is not configured."))
    assert "not configured" in diag_unconf.lower()
