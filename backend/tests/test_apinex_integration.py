"""
backend/tests/test_apinex_integration.py
----------------------------------------
Comprehensive test suite for APInex GPT-6 Luna integration:
  1. Provider Adapter (Auth, Base URL, Model ID, Non-streaming, Streaming, Error mapping)
  2. Persistent Daily Token Quota (315,000-token budget, UTC date boundaries, In-flight reservations, Concurrency safety, 80% warning)
  3. Quota-Aware Centralized Router & Fallback (Automatic fallback to NVIDIA/Groq on exhaustion/failure, Notifications, Loop prevention)
  4. Model Registry & Security Audit (No secrets, Clean model display name, No pricing / 1M / x3 metadata)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from main import app
from ai.exceptions import (
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.providers.apinex_provider import ApinexProvider
from ai.quota_manager import (
    check_quota,
    get_daily_limit,
    get_today_utc,
    get_usage,
    get_warning_threshold,
    record_usage,
    reserve_quota,
    release_reservation,
    reset_quota_for_date,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base
from ai.registry import get_master_ai_registry, get_apinex_models
from ai.config import get_model_for_task


@pytest.fixture(autouse=True)
def clean_quota_and_env(monkeypatch):
    """Isolate APInex quota in an in-memory SQLite DB so tests never pollute or wipe app.db."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr("database.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("database.engine", test_engine)
    monkeypatch.setattr("database.init_db", lambda: None)

    old_key = os.environ.get("APINEX_API_KEY")
    old_url = os.environ.get("APINEX_BASE_URL")
    old_model = os.environ.get("APINEX_MODEL_ID")
    old_limit = os.environ.get("APINEX_DAILY_TOKEN_LIMIT")
    old_enabled = os.environ.get("APINEX_ENABLED")

    # Set standard clean test environment
    os.environ["APINEX_API_KEY"] = "test-apinex-secret-key-12345"
    os.environ["APINEX_BASE_URL"] = "https://api.apinex.bond/v1"
    os.environ["APINEX_MODEL_ID"] = "free/gpt-6-luna"
    os.environ["APINEX_DAILY_TOKEN_LIMIT"] = "315000"
    os.environ["APINEX_ENABLED"] = "true"

    yield

    test_engine.dispose()
    for k, v in [
        ("APINEX_API_KEY", old_key),
        ("APINEX_BASE_URL", old_url),
        ("APINEX_MODEL_ID", old_model),
        ("APINEX_DAILY_TOKEN_LIMIT", old_limit),
        ("APINEX_ENABLED", old_enabled),
    ]:
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ── 1. PROVIDER ADAPTER TESTS ──────────────────────────────────────────────────

def test_provider_configuration_and_headers():
    provider = ApinexProvider()
    assert provider.name == "apinex"
    assert provider.get_base_url() == "https://api.apinex.bond/v1"
    assert provider.get_model_id() == "free/gpt-6-luna"
    assert provider.is_configured() is True
    assert provider._get_api_key() == "test-apinex-secret-key-12345"

    # Custom override
    with patch.dict(os.environ, {"APINEX_BASE_URL": "https://custom.endpoint.bond/v1", "APINEX_MODEL_ID": "custom-luna-id"}):
        assert provider.get_base_url() == "https://custom.endpoint.bond/v1"
        assert provider.get_model_id() == "custom-luna-id"


def test_missing_api_key_does_not_crash():
    provider = ApinexProvider()
    with patch.dict(os.environ, {"APINEX_API_KEY": ""}):
        assert provider.is_configured() is False
        with pytest.raises(ProviderUnavailable) as exc_info:
            provider.chat([{"role": "user", "content": "hi"}], model="free/gpt-6-luna")
        assert "not configured" in str(exc_info.value).lower()


def test_successful_non_streaming_response():
    provider = ApinexProvider()
    fake_body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "GPT-6 Luna response to code query."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_body

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        result = provider.chat(
            messages=[{"role": "user", "content": "Analyze repo"}],
            model="free/gpt-6-luna",
        )
        assert result == "GPT-6 Luna response to code query."

        # Verify correct URL and auth header
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.apinex.bond/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-apinex-secret-key-12345"
        assert kwargs["json"]["model"] == "free/gpt-6-luna"

    # Verify actual provider usage was persisted to DB
    usage = get_usage()
    assert usage["total_tokens"] == 200
    assert usage["prompt_tokens"] == 120
    assert usage["completion_tokens"] == 80
    assert usage["is_estimated"] is False


@pytest.mark.asyncio
async def test_successful_streaming_response():
    provider = ApinexProvider()

    lines = [
        b"data: " + json.dumps({"choices": [{"delta": {"content": "Hello "}}]}).encode("utf-8"),
        b"data: " + json.dumps({"choices": [{"delta": {"content": "world!"}}]}).encode("utf-8"),
        b"data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode("utf-8"),
        b"data: [DONE]",
    ]

    async def fake_aiter_lines():
        for line in lines:
            yield line.decode("utf-8")

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = fake_aiter_lines

    class FakeStreamContext:
        async def __aenter__(self):
            return mock_stream_resp

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def stream(self, method, url, **kwargs):
            assert url == "https://api.apinex.bond/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer test-apinex-secret-key-12345"
            assert kwargs["json"]["stream"] is True
            assert kwargs["json"]["stream_options"] == {"include_usage": True}
            return FakeStreamContext()

    with patch("httpx.AsyncClient", return_value=FakeClient()):
        chunks = []
        async for token in provider.stream_chat(
            messages=[{"role": "user", "content": "Say hello"}],
            model="free/gpt-6-luna",
        ):
            chunks.append(token)

        assert "".join(chunks) == "Hello world!"

    # Verify token usage persisted
    usage = get_usage()
    assert usage["total_tokens"] == 15
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5


def test_provider_error_mappings():
    provider = ApinexProvider()

    # 401 Unauthorized
    resp_401 = MagicMock(status_code=401, text="Unauthorized: Invalid key")
    with patch("httpx.post", return_value=resp_401):
        with pytest.raises(ProviderUnavailable) as exc:
            provider.chat([{"role": "user", "content": "hi"}], model="free/gpt-6-luna")
        assert "authentication failure" in str(exc.value).lower()

    # 429 Rate Limit
    resp_429 = MagicMock(status_code=429, text="Rate limit exceeded")
    with patch("httpx.post", return_value=resp_429):
        with pytest.raises(ProviderRateLimited) as exc:
            provider.chat([{"role": "user", "content": "hi"}], model="free/gpt-6-luna")
        assert "rate limit" in str(exc.value).lower()

    # 404 Model Not Found
    resp_404 = MagicMock(status_code=404, text="Model not found")
    with patch("httpx.post", return_value=resp_404):
        with pytest.raises(ProviderUnavailable) as exc:
            provider.chat([{"role": "user", "content": "hi"}], model="free/gpt-6-luna")
        assert "model not found" in str(exc.value).lower()

    # 500 Server Error
    resp_500 = MagicMock(status_code=500, text="Internal server error")
    with patch("httpx.post", return_value=resp_500):
        with pytest.raises(ProviderUnavailable) as exc:
            provider.chat([{"role": "user", "content": "hi"}], model="free/gpt-6-luna")
        assert "server error" in str(exc.value).lower()


# ── 2. PERSISTENT DAILY QUOTA COUNTER TESTS ────────────────────────────────────

def test_quota_initial_state():
    usage = get_usage()
    assert usage["daily_limit"] == 315000
    assert usage["total_tokens"] == 0
    assert usage["remaining_tokens"] == 315000
    assert usage["percent_used"] == 0.0
    assert usage["is_exhausted"] is False
    assert usage["warning"] is False


def test_quota_recording_and_persistence():
    # Record first request: 50,000 tokens
    record_usage(total_tokens=50000, prompt_tokens=30000, completion_tokens=20000)
    usage = get_usage()
    assert usage["total_tokens"] == 50000
    assert usage["remaining_tokens"] == 265000
    assert usage["request_count"] == 1

    # Record second request: 100,000 tokens
    record_usage(total_tokens=100000, prompt_tokens=60000, completion_tokens=40000)
    usage = get_usage()
    assert usage["total_tokens"] == 150000
    assert usage["remaining_tokens"] == 165000
    assert usage["request_count"] == 2
    assert usage["percent_used"] == round((150000 / 315000) * 100, 2)


def test_quota_warning_threshold_at_80_percent():
    # 80% of 315,000 = 252,000 tokens
    record_usage(total_tokens=251000)
    usage = get_usage()
    assert usage["warning"] is False
    assert usage["is_exhausted"] is False

    # Pass 80% threshold
    record_usage(total_tokens=2000)  # total 253,000 tokens (> 80%)
    usage = get_usage()
    assert usage["warning"] is True
    assert usage["is_exhausted"] is False


def test_quota_pass_through_past_315k_and_hard_limit_mode():
    # Consume 315,000 tokens
    record_usage(total_tokens=315000)
    usage = get_usage()
    assert usage["is_exhausted"] is True
    assert usage["remaining_tokens"] == 0

    # In pass-through mode (default), requests past 315k proceed to upstream
    can_proceed, reason, _ = check_quota(estimated_tokens=500)
    assert can_proceed is True
    assert "pass-through active" in reason.lower()

    # When hard limit is explicitly enforced, requests are blocked locally
    with patch.dict(os.environ, {"APINEX_ENFORCE_HARD_LIMIT": "true"}):
        can_proceed_hard, reason_hard, _ = check_quota(estimated_tokens=500)
        assert can_proceed_hard is False
        assert "daily token limit" in reason_hard.lower()


def test_in_flight_reservations():
    # In hard-limit mode, reservations beyond budget are rejected
    with patch.dict(os.environ, {"APINEX_ENFORCE_HARD_LIMIT": "true"}):
        # Limit is 315,000. Consume 314,800 tokens (200 tokens remaining)
        record_usage(total_tokens=314800)

        # Attempting to reserve 500 tokens should fail
        ok = reserve_quota(estimated_tokens=500)
        assert ok is False

        # Attempting to reserve 100 tokens should succeed
        ok = reserve_quota(estimated_tokens=100)
        assert ok is True

        # After reserving 100, attempting to reserve another 150 should fail (100 in flight + 150 = 250 > 200)
        ok2 = reserve_quota(estimated_tokens=150)
        assert ok2 is False

        # Releasing reservation allows new reservation
        release_reservation(estimated_tokens=100)
        ok3 = reserve_quota(estimated_tokens=150)
        assert ok3 is True
        release_reservation(estimated_tokens=150)


def test_quota_date_scoping_utc():
    today = get_today_utc()
    record_usage(total_tokens=10000, target_date=today)
    
    # Query today
    today_usage = get_usage(today)
    assert today_usage["total_tokens"] == 10000

    # Query yesterday or another date
    other_date = "2025-01-01"
    other_usage = get_usage(other_date)
    assert other_usage["total_tokens"] == 0


# ── 3. ROUTING AND FALLBACK TESTS ─────────────────────────────────────────────

def test_routing_pass_through_past_315k_and_fallback_chain():
    # Fill APInex quota to 315,000 tokens
    record_usage(total_tokens=315000)

    # In pass-through mode, APInex remains primary while healthy
    decision = get_model_for_task(
        task="CODEBASE_CHAT",
        user_preferred_provider="apinex",
        user_preferred_model="free/gpt-6-luna",
    )
    assert decision["provider"] == "apinex"
    assert decision["modelId"] == "free/gpt-6-luna"

    # Fallback chain must have NVIDIA first, then Groq
    fb_chain = decision.get("fallbackChain", [])
    assert len(fb_chain) >= 2
    assert fb_chain[0]["provider"] == "nvidia"
    assert fb_chain[1]["provider"] == "groq"


def test_routing_fallback_when_apinex_stops_working():
    from ai.router import record_model_error
    from ai.exceptions import ProviderRateLimited

    # Simulate APInex encountering provider-side 429 rate limit or outage
    record_model_error("apinex", "free/gpt-6-luna", ProviderRateLimited("rate limited", provider="apinex"), status_code=429)

    decision = get_model_for_task(
        task="CODEBASE_CHAT",
        user_preferred_provider="apinex",
        user_preferred_model="free/gpt-6-luna",
    )

    # Automatically promoted to NVIDIA primary with Groq fallback
    assert decision["provider"] == "nvidia"
    assert "APInex stopped responding" in decision["reason"]
    fb_chain = decision.get("fallbackChain", [])
    assert any(fb["provider"] == "groq" for fb in fb_chain)


def test_model_registry_includes_apinex_without_prohibited_metadata():
    registry = get_master_ai_registry()
    assert "providers" in registry
    assert "providers_map" in registry

    providers = registry["providers_map"]
    assert "apinex" in providers
    assert "nvidia" in providers
    assert "groq" in providers

    apinex = providers["apinex"]
    assert apinex["id"] == "apinex"
    assert apinex["displayName"] == "APInex"
    assert len(apinex["models"]) == 1

    model = apinex["models"][0]
    assert model["id"] == "free/gpt-6-luna"
    assert model["displayName"] == "GPT-6 Luna"
    assert model["providerId"] == "apinex"

    # SECURITY AUDIT: Verify no pricing, context window 1M, or weight multiplier x3 in output
    serialized = json.dumps(apinex)
    assert "1000000" not in serialized
    assert "1M" not in serialized
    assert "x3" not in serialized
    assert "×3" not in serialized
    assert "price" not in serialized.lower()


# ── 4. API ENDPOINT TESTS ──────────────────────────────────────────────────────

def test_quota_api_endpoints():
    client = TestClient(app)

    record_usage(total_tokens=12345, prompt_tokens=8000, completion_tokens=4345)

    # GET /ai/apinex/quota
    resp = client.get("/ai/apinex/quota")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "apinex"
    assert data["model"] == "free/gpt-6-luna"
    assert data["total_tokens"] == 12345
    assert data["daily_limit"] == 315000
    assert data["remaining_tokens"] == 315000 - 12345
    assert "api_key" not in data
    assert "secret" not in json.dumps(data).lower()

    # GET /ai/quota/apinex (alias)
    resp_alias = client.get("/ai/quota/apinex")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["total_tokens"] == 12345


def test_security_audit_api_key_not_exposed():
    client = TestClient(app)

    # /ai/models endpoint
    resp = client.get("/ai/models")
    assert resp.status_code == 200
    text = resp.text
    assert "test-apinex-secret-key-12345" not in text

    # /ai/apinex/quota endpoint
    resp2 = client.get("/ai/apinex/quota")
    assert resp2.status_code == 200
    assert "test-apinex-secret-key-12345" not in resp2.text
