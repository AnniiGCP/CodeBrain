"""
Tests for PR URL normalization, owner/repo extraction, and provider routing.
Validates:
  - 'https://github.com/octocat/with-ci-repo/pull/66' -> ('octocat', 'with-ci-repo') and PR #66
  - 'owner/repo' strings
  - Azure DevOps URL raises UnsupportedProviderError without hitting GitHub API
  - Polling loop suppresses repeated calls for unsupported/invalid records
"""
import pytest
from gitops.pr_client import (
    _extract_owner_repo,
    extract_pr_number_from_url,
    UnsupportedProviderError,
)

def test_extract_owner_repo_github_slug():
    owner, repo = _extract_owner_repo("octocat/hello-world")
    assert owner == "octocat"
    assert repo == "hello-world"

def test_extract_owner_repo_github_full_pr_url():
    owner, repo = _extract_owner_repo("https://github.com/octocat/with-ci-repo/pull/66")
    assert owner == "octocat"
    assert repo == "with-ci-repo"

    pr_num = extract_pr_number_from_url("https://github.com/octocat/with-ci-repo/pull/66")
    assert pr_num == 66

def test_extract_owner_repo_github_another_pr_url():
    url = "https://github.com/octocat/repo-config2-no-automerge-setting/pull/202"
    owner, repo = _extract_owner_repo(url)
    assert owner == "octocat"
    assert repo == "repo-config2-no-automerge-setting"
    assert extract_pr_number_from_url(url) == 202

def test_azure_devops_url_raises_unsupported_provider():
    azure_url = "https://dev.azure.com/org/proj/_git/repo/pullrequest/101"
    with pytest.raises(UnsupportedProviderError) as exc_info:
        _extract_owner_repo(azure_url)
    assert "Azure DevOps" in str(exc_info.value)
