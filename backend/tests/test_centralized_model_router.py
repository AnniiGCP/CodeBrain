"""
backend/tests/test_centralized_model_router.py
----------------------------------------------
Comprehensive verification suite for the Centralized AI Model Router,
NVIDIA-Primary / Groq-Fallback policy, task allocation, and health tracking.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient
from main import app
from ai.config import (
    get_model_for_task,
    getModelForTask,
    record_model_error,
    record_model_success,
    get_model_health,
    TASK_ROUTING_SPEC,
)
from ai.router import _execute_chat, route_chat, route_reasoning
from ai.exceptions import AllProvidersFailedError, ProviderTimeout, ProviderUnavailable


def test_task_routing_matrix_coverage():
    """Verify all required tasks map to the exact prompt specifications."""
    expected_primary = {
        "DOCUMENTATION": ("nvidia", "glm-5-3"),
        "DOCUMENTATION_REFINEMENT": ("nvidia", "glm-5-3"),
        "PROJECT_OVERVIEW": ("nvidia", "glm-5-3"),
        "TECHNOLOGY_STACK": ("nvidia", "glm-5-3"),
        "REPOSITORY_ANALYSIS": ("nvidia", "deepseek-v4.1-flash"),
        "ARCHITECTURE": ("nvidia", "glm-5-3"),
        "DIAGRAM": ("nvidia", "glm-5-3"),
        "API_ANALYSIS": ("nvidia", "deepseek-v4.1-flash"),
        "API_DOCUMENTATION": ("nvidia", "glm-5-3"),
        "DATABASE_DISCOVERY": ("nvidia", "deepseek-v4.1-flash"),
        "DATABASE_DOCUMENTATION": ("nvidia", "glm-5-3"),
        "DEPENDENCY_DISCOVERY": ("nvidia", "deepseek-v4.1-flash"),
        "DEPENDENCY_EXPLANATION": ("nvidia", "glm-5-3"),
        "CODEBASE_CHAT": ("nvidia", "deepseek-v4.1-flash"),
        "FAST_CHAT": ("nvidia", "glm-5-3-flash"),
        "COMPLEX_TECHNICAL_CHAT": ("nvidia", "glm-5-3"),
        "CODE_EXPLANATION": ("nvidia", "deepseek-v4.1-flash"),
        "COMPLEX_CODE_EXPLANATION": ("nvidia", "glm-5-3"),
        "ERROR_ANALYSIS": ("nvidia", "deepseek-v4.1-flash"),
        "SCREENSHOT_ANALYSIS": ("nvidia", "deepseek-v4.1-flash"),
        "ROOT_CAUSE_ANALYSIS": ("nvidia", "glm-5-3"),
        "CODE_FIX_PLANNING": ("nvidia", "glm-5-3"),
        "CODE_FIX": ("nvidia", "glm-5-3"),
        "MULTI_FILE_FIXING": ("nvidia", "glm-5-3"),
        "TEST_GENERATION": ("nvidia", "glm-5-3"),
        "TEST_FAILURE_REPAIR": ("nvidia", "glm-5-3"),
        "DOCKER": ("nvidia", "glm-5-3"),
        "KUBERNETES": ("nvidia", "glm-5-3"),
        "GITHUB_ACTIONS": ("nvidia", "glm-5-3"),
        "AZURE_DEVOPS": ("nvidia", "glm-5-3"),
        "CI_CD": ("nvidia", "glm-5-3"),
        "TERRAFORM": ("nvidia", "glm-5-3"),
        "GIT": ("nvidia", "glm-5-3"),
        "COMMIT_MESSAGE": ("nvidia", "glm-5-3-flash"),
        "README": ("nvidia", "glm-5-3"),
        "SUMMARY": ("nvidia", "glm-5-3-flash"),
        "COMPLEX_SUMMARY": ("nvidia", "glm-5-3"),
        "LARGE_REPOSITORY_ANALYSIS": ("nvidia", "nemotron-3-ultra-550b-a55b"),
    }

    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "nvidia"}):
        for task_name, (expected_prov, expected_model) in expected_primary.items():
            decision = get_model_for_task(task_name)
            assert decision["provider"] == expected_prov, f"Task {task_name} provider mismatch"
            assert decision["modelId"] == expected_model, f"Task {task_name} model mismatch"
            assert len(decision["fallbackChain"]) >= 2, f"Task {task_name} should have fallback chain"


def test_groq_fallback_models_assigned():
    """Verify Groq fallback models match engineering vs fast allocations."""
    # Serious engineering tasks must fallback to GPT-OSS 120B
    doc_decision = get_model_for_task("DOCUMENTATION")
    groq_fb = [fb for fb in doc_decision["fallbackChain"] if fb["provider"] == "groq"]
    assert any(fb["modelId"] == "openai/gpt-oss-120b" for fb in groq_fb)

    # Lightweight fast tasks must fallback to GPT-OSS 20B
    fast_decision = get_model_for_task("FAST_CHAT")
    groq_fast_fb = [fb for fb in fast_decision["fallbackChain"] if fb["provider"] == "groq"]
    assert any(fb["modelId"] == "openai/gpt-oss-20b" for fb in groq_fast_fb)


def test_context_size_routes_to_nemotron():
    """Verify context size > threshold routes to Nemotron 3 Ultra."""
    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "nvidia"}):
        normal = get_model_for_task("CODE_FIX", context_size=5000)
        assert normal["modelId"] == "glm-5-3"

        huge = get_model_for_task("CODE_FIX", context_size=80000)
        assert huge["modelId"] == "nemotron-3-ultra-550b-a55b"
        assert "Nemotron 3 Ultra" in huge["displayName"]


def test_vision_modality_routing():
    """Verify vision requirement allocates DeepSeek V4.1 Flash with Llama 3.2 Vision alternate."""
    decision = get_model_for_task("ERROR_ANALYSIS", requires_vision=True)
    assert decision["provider"] == "nvidia"
    assert decision["modelId"] == "deepseek-v4.1-flash"

    alts = [fb for fb in decision["fallbackChain"] if fb["provider"] == "nvidia"]
    assert any(alt["modelId"] == "meta/llama-3.2-11b-vision-instruct" for alt in alts)


def test_model_health_promotion_on_degradation():
    """Verify health degradation on primary promotes alternate model."""
    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "nvidia"}):
        record_model_error("nvidia", "glm-5-3", Exception("Rate limited"), status_code=429)
        assert get_model_health("nvidia", "glm-5-3") == "RATE_LIMITED"

        # Should promote alternate (DeepSeek V4.1 Flash)
        decision = get_model_for_task("DOCUMENTATION")
        assert decision["modelId"] == "deepseek-v4.1-flash"

        # Reset health on success
        record_model_success("nvidia", "glm-5-3", latency_ms=450)
        assert get_model_health("nvidia", "glm-5-3") == "AVAILABLE"

        # Restores GLM 5.3 as primary
        recovered = get_model_for_task("DOCUMENTATION")
        assert recovered["modelId"] == "glm-5-3"


def test_multistage_fallback_execution():
    """Verify execution cascade: NVIDIA Primary -> NVIDIA Alternate -> Groq Fallback."""
    messages = [{"role": "user", "content": "hello"}]

    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "nvidia"}), patch("ai.router._PROVIDERS") as mock_providers:
        mock_nvd = MagicMock()
        mock_groq = MagicMock()
        mock_providers.get.side_effect = lambda name: mock_nvd if name == "nvidia" else mock_groq

        # Case 1: Primary succeeds
        mock_nvd.chat.return_value = "Primary success"
        res = _execute_chat("DOCUMENTATION", messages)
        assert res == "Primary success"

        # Case 2: Primary fails, alternate NVIDIA succeeds
        mock_nvd.chat.side_effect = [ProviderTimeout("NIM Timeout", provider="nvidia"), "Alternate success"]
        res2 = _execute_chat("DOCUMENTATION", messages)
        assert res2 == "Alternate success"

        # Case 3: Both NVIDIA primary & alternate fail, Groq fallback succeeds
        mock_nvd.chat.side_effect = ProviderUnavailable("NIM 503", provider="nvidia")
        mock_groq.chat.return_value = "Groq fallback success"
        res3 = _execute_chat("DOCUMENTATION", messages)
        assert res3 == "Groq fallback success"
        from ai.config import _MODEL_HEALTH
        _MODEL_HEALTH.clear()


def test_api_endpoint_model_for_task():
    """Verify GET /ai/model-for-task API endpoint."""
    from ai.config import _MODEL_HEALTH
    _MODEL_HEALTH.clear()
    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "nvidia"}):
        client = TestClient(app)
        resp = client.get("/ai/model-for-task?task=DOCUMENTATION")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "nvidia"
        assert data["modelId"] == "glm-5-3"
        assert "fallbackChain" in data
        assert len(data["fallbackChain"]) >= 2


def test_apinex_primary_policy_everywhere():
    """Verify APInex is primary across tasks when AI_PRIMARY_PROVIDER is apinex."""
    with patch.dict("os.environ", {"AI_PRIMARY_PROVIDER": "apinex", "APINEX_MODEL_ID": "free/gpt-6-luna"}):
        for task in ("DOCUMENTATION", "CODE_FIX", "ERROR_ANALYSIS", "PROJECT_OVERVIEW"):
            d = get_model_for_task(task)
            assert d["provider"] == "apinex"
            assert d["modelId"] == "free/gpt-6-luna"
            assert len(d["fallbackChain"]) >= 2
            assert d["fallbackChain"][0]["provider"] == "nvidia"
            assert d["fallbackChain"][1]["provider"] == "groq"


def test_user_provided_endpoint_primacy_across_sources():
    """Verify that when user specifies an OpenAI-compatible or Anthropic-compatible custom endpoint,
    that custom model takes absolute precedence across all tasks (chat, code fix, doc gen, error analysis),
    and falls back to developer defaults (APInex -> NVIDIA -> Groq)."""
    custom_prov = "openai-compatible"
    custom_model = "my-custom-qwen-coder"

    for task in ("CODE_FIX", "DOCUMENTATION", "CODEBASE_CHAT", "ERROR_ANALYSIS"):
        d = get_model_for_task(
            task,
            user_preferred_provider=custom_prov,
            user_preferred_model=custom_model,
        )
        assert d["provider"] == custom_prov
        assert d["modelId"] == custom_model
        # First fallback is APInex, followed by NVIDIA
        assert len(d["fallbackChain"]) >= 2
        assert d["fallbackChain"][0]["provider"] == "apinex"

    # Test Anthropic-compatible custom endpoint
    anth_prov = "anthropic-compatible"
    anth_model = "claude-3-7-sonnet"
    for task in ("CODE_FIX", "DOCUMENTATION", "CODEBASE_CHAT"):
        d = get_model_for_task(
            task,
            user_preferred_provider=anth_prov,
            user_preferred_model=anth_model,
        )
        assert d["provider"] == anth_prov
        assert d["modelId"] == anth_model
        assert d["fallbackChain"][0]["provider"] == "apinex"

