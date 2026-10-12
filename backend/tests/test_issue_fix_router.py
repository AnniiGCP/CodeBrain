"""
backend/tests/test_issue_fix_router.py
--------------------------------------
Comprehensive test suite verifying authoritative issue-fixing routing order:
  1. APInex (free/gpt-6-luna) attempted first
  2. NVIDIA (configured primary fallback model) attempted second
  3. Groq (configured secondary fallback model) attempted third
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from ai.exceptions import AllProvidersFailedError, ProviderTimeout, ProviderUnavailable
from ai.issue_fix_router import (
    clean_and_normalize_diff,
    route_issue_fix,
    IssueFixResult,
)


SAMPLE_VALID_DIFF = """--- a/src/auth.py
+++ b/src/auth.py
@@ -10,4 +10,4 @@
-def check_token(t):
-    return t == SECRET
+def check_token(t):
+    return hmac.compare_digest(t, SECRET)
"""

SAMPLE_WRONG_FILE_DIFF = """--- a/src/other.py
+++ b/src/other.py
@@ -1,3 +1,3 @@
-x = 1
+x = 2
"""


@pytest.fixture(autouse=True)
def reset_health():
    from ai.config import _MODEL_HEALTH
    _MODEL_HEALTH.clear()
    yield
    _MODEL_HEALTH.clear()


def test_clean_and_normalize_diff_valid():
    cleaned, valid = clean_and_normalize_diff(SAMPLE_VALID_DIFF, expected_file_path="src/auth.py")
    assert valid is True
    assert "--- a/src/auth.py" in cleaned
    assert "hmac.compare_digest" in cleaned


def test_clean_and_normalize_diff_markdown_fences():
    wrapped = f"Here is the diff to fix the issue:\n```diff\n{SAMPLE_VALID_DIFF}\n```\nHope this helps!"
    cleaned, valid = clean_and_normalize_diff(wrapped, expected_file_path="src/auth.py")
    assert valid is True
    assert cleaned.startswith("--- a/src/auth.py")


def test_clean_and_normalize_diff_rejects_empty_or_prose():
    prose = "I looked at the issue. To fix it, you should import hmac and use compare_digest."
    cleaned, valid = clean_and_normalize_diff(prose, expected_file_path="src/auth.py")
    assert valid is False


def test_clean_and_normalize_diff_rejects_wrong_file():
    cleaned, valid = clean_and_normalize_diff(SAMPLE_WRONG_FILE_DIFF, expected_file_path="src/auth.py")
    assert valid is False


def test_clean_and_normalize_diff_full_file_replacement_synthesizes_diff():
    orig_code = "def check(a):\n    return a == 1\n"
    new_code = "def check(a):\n    return a == 2\n"
    wrapped = f"```python\n{new_code}```"
    cleaned, valid = clean_and_normalize_diff(wrapped, expected_file_path="app.py", source_code=orig_code)
    assert valid is True
    assert "--- a/app.py" in cleaned
    assert "+    return a == 2" in cleaned


def test_issue_fix_order_apinex_first_success():
    """APInex succeeds on attempt 1 -> NVIDIA and Groq must NOT be called."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-test-key",
            "APINEX_MODEL_ID": "free/gpt-6-luna",
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
            "GROQ_API_KEY": "gsk-test-key",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(True, "", {"is_exhausted": False})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_apinex = MagicMock()
        mock_nvidia = MagicMock()
        mock_groq = MagicMock()

        def _prov_lookup(name):
            if name == "apinex":
                return mock_apinex
            if name == "nvidia":
                return mock_nvidia
            return mock_groq

        mock_get_provider.side_effect = _prov_lookup
        mock_apinex.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "apinex"
        assert res.model == "free/gpt-6-luna"
        assert res.fallback_used is False
        assert "Fixed using APInex GPT-6 Luna" in res.fix_attribution
        assert len(res.attempts) == 1
        assert res.attempts[0]["status"] == "success"

        # NVIDIA and Groq must not have been called
        mock_nvidia.chat.assert_not_called()
        mock_groq.chat.assert_not_called()


def test_issue_fix_order_apinex_fails_nvidia_succeeds():
    """APInex fails (timeout/error) -> NVIDIA succeeds on attempt 2."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-test-key",
            "APINEX_MODEL_ID": "free/gpt-6-luna",
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
            "AI_CODE_MODEL": "glm-5-3",
            "GROQ_API_KEY": "gsk-test-key",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(True, "", {"is_exhausted": False})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_apinex = MagicMock()
        mock_nvidia = MagicMock()
        mock_groq = MagicMock()

        def _prov_lookup(name):
            if name == "apinex":
                return mock_apinex
            if name == "nvidia":
                return mock_nvidia
            return mock_groq

        mock_get_provider.side_effect = _prov_lookup
        mock_apinex.chat.side_effect = ProviderTimeout("APInex request timed out", provider="apinex")
        mock_nvidia.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "nvidia"
        assert res.model == "glm-5-3"
        assert res.fallback_used is True
        assert "APInex unavailable — fixed using NVIDIA" in res.fix_attribution
        assert len(res.attempts) == 2
        assert res.attempts[0]["status"] == "failed"
        assert res.attempts[0]["provider"] == "apinex"
        assert res.attempts[1]["status"] == "success"
        assert res.attempts[1]["provider"] == "nvidia"

        mock_groq.chat.assert_not_called()


def test_issue_fix_order_apinex_unusable_patch_falls_back_to_nvidia():
    """APInex returns HTTP 200 with pure prose (no valid diff) -> cascades to NVIDIA."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-test-key",
            "APINEX_MODEL_ID": "free/gpt-6-luna",
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
            "AI_CODE_MODEL": "glm-5-3",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(True, "", {"is_exhausted": False})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_apinex = MagicMock()
        mock_nvidia = MagicMock()

        mock_get_provider.side_effect = lambda name: mock_apinex if name == "apinex" else mock_nvidia
        mock_apinex.chat.return_value = "I think you should change == to hmac.compare_digest in your function."
        mock_nvidia.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "nvidia"
        assert len(res.attempts) == 2
        assert res.attempts[0]["status"] == "failed"
        assert res.attempts[0]["failure_category"] == "INVALID_PATCH"
        assert res.attempts[1]["status"] == "success"


def test_issue_fix_order_apinex_and_nvidia_fail_groq_succeeds():
    """Both APInex and NVIDIA fail -> Groq succeeds on attempt 3."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-test-key",
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
            "GROQ_API_KEY": "gsk-test-key",
            "AI_GROQ_CODE_MODEL": "openai/gpt-oss-120b",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(True, "", {"is_exhausted": False})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_apinex = MagicMock()
        mock_nvidia = MagicMock()
        mock_groq = MagicMock()

        def _prov_lookup(name):
            if name == "apinex":
                return mock_apinex
            if name == "nvidia":
                return mock_nvidia
            return mock_groq

        mock_get_provider.side_effect = _prov_lookup
        mock_apinex.chat.side_effect = ProviderUnavailable("APInex 503", provider="apinex")
        mock_nvidia.chat.side_effect = ProviderUnavailable("NVIDIA 503", provider="nvidia")
        mock_groq.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "groq"
        assert res.model == "openai/gpt-oss-120b"
        assert res.fallback_used is True
        assert "APInex and NVIDIA failed — fixed using Groq" in res.fix_attribution
        assert len(res.attempts) == 3
        assert res.attempts[0]["status"] == "failed"
        assert res.attempts[1]["status"] == "failed"
        assert res.attempts[2]["status"] == "success"


def test_issue_fix_order_unconfigured_apinex_skips_to_nvidia():
    """When APInex has no API key configured, it is recorded as skipped and NVIDIA is called."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_API_KEY": "",  # Unconfigured
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
            "GROQ_API_KEY": "gsk-test-key",
        },
    ), patch("ai.router._get_provider") as mock_get_provider:
        mock_nvidia = MagicMock()
        mock_get_provider.return_value = mock_nvidia
        mock_nvidia.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "nvidia"
        assert res.attempts[0]["provider"] == "apinex"
        assert res.attempts[0]["status"] == "skipped"
        assert res.attempts[0]["failure_category"] == "UNCONFIGURED"
        assert res.attempts[1]["provider"] == "nvidia"
        assert res.attempts[1]["status"] == "success"


def test_issue_fix_order_quota_exhausted_skips_to_nvidia():
    """When APInex daily token limit is exhausted, APInex is skipped and NVIDIA is attempted."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-valid",
            "NVIDIA_NIM_API_KEY": "nvapi-test-key",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(False, "Daily limit exhausted", {"is_exhausted": True})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_nvidia = MagicMock()
        mock_get_provider.return_value = mock_nvidia
        mock_nvidia.chat.return_value = SAMPLE_VALID_DIFF

        res = route_issue_fix(messages, expected_file_path="src/auth.py")

        assert res.provider == "nvidia"
        assert res.attempts[0]["provider"] == "apinex"
        assert res.attempts[0]["status"] == "skipped"
        assert res.attempts[0]["failure_category"] == "QUOTA_EXHAUSTED"
        assert res.attempts[1]["provider"] == "nvidia"
        assert res.attempts[1]["status"] == "success"


def test_issue_fix_order_all_providers_fail():
    """When all 3 providers fail, raises AllProvidersFailedError with trace."""
    messages = [{"role": "user", "content": "fix issue"}]

    with patch.dict(
        os.environ,
        {
            "APINEX_ENABLED": "true",
            "APINEX_API_KEY": "sk-apx-test",
            "NVIDIA_NIM_API_KEY": "nvapi-test",
            "GROQ_API_KEY": "gsk-test",
        },
    ), patch("ai.issue_fix_router.check_quota", return_value=(True, "", {"is_exhausted": False})), patch(
        "ai.router._get_provider"
    ) as mock_get_provider:
        mock_prov = MagicMock()
        mock_get_provider.return_value = mock_prov
        mock_prov.chat.side_effect = ProviderUnavailable("Provider down", provider="mock")

        with pytest.raises(AllProvidersFailedError) as exc_info:
            route_issue_fix(messages, expected_file_path="src/auth.py")

        assert "Issue-Fix AI Routing Failure" in str(exc_info.value)
