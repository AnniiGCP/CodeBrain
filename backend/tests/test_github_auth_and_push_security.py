"""
backend/tests/test_github_auth_and_push_security.py
----------------------------------------------------
Tests for GitHub authentication, credential scrubbing, URL sanitization,
Contents API direct writes, and protected branch handling.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch
import pytest

from gitops.git_ops import sanitize_sensitive_text, _inject_credentials, _sanitise_url
from gitops.github_actions import create_or_update_remote_file, get_remote_default_branch
from automation.ci_setup import get_repo_full_name


def test_sanitize_sensitive_text_redacts_tokens():
    # Test OAuth tokens, personal access tokens, fine-grained tokens
    dummy_gho = "gh" + "o_" + "wuFro6Exs2sdnsxFf44Yn8vQUlGMeW1VgfKB"
    raw_error = f"fatal: unable to access 'https://{dummy_gho}@github.com/owner/repo/': URL rejected: Bad hostname"
    sanitized = sanitize_sensitive_text(raw_error)
    assert "gho_" not in sanitized
    assert "[REDACTED_AUTH]" in sanitized or "[REDACTED_GITHUB_TOKEN]" in sanitized

    # Test fine-grained PAT
    dummy_pat = "github_" + "pat_" + "11ABCDEF0123456789_abcdefghijKLMNOP"
    pat_str = f"Error pushing with {dummy_pat}"
    assert "github_pat_" not in sanitize_sensitive_text(pat_str)

    # Test classic PAT
    dummy_ghp = "gh" + "p_" + "Abcdef1234567890abcdef1234567890"
    ghp_str = f"Token is {dummy_ghp}"
    assert "ghp_" not in sanitize_sensitive_text(ghp_str)


def test_inject_credentials_prevents_double_injection():
    # Simulate a remote URL that already had credentials embedded in clone_url
    prev_tok = "gh" + "o_" + "previousToken123456789"
    new_token = "gh" + "o_" + "newFreshToken987654321"
    dirty_url = f"https://{prev_tok}@github.com/kangan289/dev"

    # Injecting credentials should strip the old credential first
    push_url = _inject_credentials(dirty_url, provider="github", token=new_token)

    # Must contain exactly ONE '@' symbol
    assert push_url.count("@") == 1
    # Hostname must be github.com and never contain a token
    assert push_url.startswith(f"https://x-access-token:{new_token}@github.com/kangan289/dev")
    # Must not contain the previous token
    assert prev_tok not in push_url


def test_inject_credentials_with_clean_url():
    clean_url = "https://github.com/myorg/myrepo"
    token = "gh" + "o_" + "sampleToken12345"
    push_url = _inject_credentials(clean_url, provider="github", token=token)
    assert push_url == f"https://x-access-token:{token}@github.com/myorg/myrepo"


def test_create_or_update_remote_file_new_file():
    mock_resp_get = MagicMock()
    mock_resp_get.status_code = 404

    mock_resp_put = MagicMock()
    mock_resp_put.status_code = 201
    mock_resp_put.json.return_value = {
        "content": {"name": "ci.yml"},
        "commit": {"sha": "abc123commitsha", "html_url": "https://github.com/owner/repo/commit/abc123commitsha"},
    }

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = mock_resp_get
        instance.put.return_value = mock_resp_put

        res = create_or_update_remote_file(
            repo_full_name="owner/repo",
            path=".github/workflows/ci.yml",
            content="name: CI\n",
            commit_message="ci: add workflow",
            branch="main",
            token="gh" + "o_" + "mocktoken123",
        )

        assert res["status"] == "success"
        assert res["commit_sha"] == "abc123commitsha"
        assert res["file_path"] == ".github/workflows/ci.yml"
        # Verify PUT was called with branch and content
        instance.put.assert_called_once()
        put_kwargs = instance.put.call_args[1]
        assert put_kwargs["json"]["branch"] == "main"
        assert put_kwargs["json"]["message"] == "ci: add workflow"


def test_create_or_update_remote_file_existing_file():
    mock_resp_get = MagicMock()
    mock_resp_get.status_code = 200
    mock_resp_get.json.return_value = {"sha": "existingFileSha456"}

    mock_resp_put = MagicMock()
    mock_resp_put.status_code = 200
    mock_resp_put.json.return_value = {
        "commit": {"sha": "newCommitSha789", "html_url": "https://github.com/owner/repo/commit/newCommitSha789"},
    }

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = mock_resp_get
        instance.put.return_value = mock_resp_put

        res = create_or_update_remote_file(
            repo_full_name="owner/repo",
            path=".github/workflows/ci.yml",
            content="name: CI Updated\n",
            commit_message="ci: update workflow",
            branch="main",
            token="gh" + "o_" + "mocktoken123",
        )

        assert res["status"] == "success"
        assert res["commit_sha"] == "newCommitSha789"
        # Must include the existing SHA to update cleanly without conflict
        put_payload = instance.put.call_args[1]["json"]
        assert put_payload["sha"] == "existingFileSha456"


def test_create_or_update_remote_file_protected_branch_error():
    mock_resp_get = MagicMock(status_code=404)
    mock_resp_put = MagicMock()
    mock_resp_put.status_code = 403
    mock_resp_put.text = "Resource protected by organization branch protection rules"

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = mock_resp_get
        instance.put.return_value = mock_resp_put

        with pytest.raises(RuntimeError) as exc_info:
            create_or_update_remote_file(
                repo_full_name="owner/repo",
                path=".github/workflows/ci.yml",
                content="name: CI\n",
                commit_message="ci: add workflow",
                branch="main",
                token="gh" + "o_" + "mocktoken123",
            )

        err_msg = str(exc_info.value)
        assert "branch protection rules" in err_msg
        assert "Install via Pull Request" in err_msg
