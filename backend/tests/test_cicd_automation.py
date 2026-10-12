"""
Tests for CodeBrain Repository-Aware CI/CD Automation System.
Covers:
  - Multi-repository isolation
  - Evidence-based workflow generation & validation
  - Failure classification & unfixable blocker detection
  - Bounded retry policy & infinite loop prevention
  - Deployment configuration detection
"""
import json
import pytest
from pathlib import Path
import tempfile
import shutil

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, User, Repo, RepoFile, RepoCiConfig, RepoCiRun
from automation.ci_setup import (
    analyze_repository_evidence,
    generate_default_ci_workflow,
    _validate_workflow_yaml,
    get_or_create_repo_ci_config,
)
from automation.ci_diagnosis import (
    classify_failure_logs,
    compute_failure_fingerprint,
    extract_failing_lines,
)
from automation.deployment_detector import detect_repository_deployment


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def test_user(db_session):
    user = User(id="user-123", github_id="gh-123", github_username="developer")
    db_session.add(user)
    db_session.commit()
    return user


def test_repository_isolation(db_session, test_user):
    """
    Ensure two different repositories maintain independent CI configs,
    workflows, retry budgets, and states without leakage.
    """
    repo_a = Repo(id="repo-a", user_id=test_user.id, name="backend-service", source_type="github")
    repo_b = Repo(id="repo-b", user_id=test_user.id, name="frontend-app", source_type="github")
    db_session.add_all([repo_a, repo_b])
    db_session.commit()

    config_a = get_or_create_repo_ci_config(repo_a, db_session)
    config_b = get_or_create_repo_ci_config(repo_b, db_session)

    config_a.workflow_path = ".github/workflows/backend.yml"
    config_a.setup_status = "installed"
    config_a.current_retry_count = 2

    config_b.workflow_path = ".github/workflows/frontend.yml"
    config_b.setup_status = "proposed"
    config_b.current_retry_count = 0

    db_session.commit()

    reloaded_a = get_or_create_repo_ci_config(repo_a, db_session)
    reloaded_b = get_or_create_repo_ci_config(repo_b, db_session)

    assert reloaded_a.workflow_path == ".github/workflows/backend.yml"
    assert reloaded_a.setup_status == "installed"
    assert reloaded_a.current_retry_count == 2

    assert reloaded_b.workflow_path == ".github/workflows/frontend.yml"
    assert reloaded_b.setup_status == "proposed"
    assert reloaded_b.current_retry_count == 0


def test_evidence_based_workflow_generation(db_session, test_user):
    """
    Verify that Python and Node projects receive tailored workflows
    with pinned action versions, least-privilege permissions, and workflow_dispatch.
    """
    repo = Repo(id="repo-py", user_id=test_user.id, name="python-api", source_type="github")
    db_session.add(repo)
    db_session.commit()

    # Add Python files to RepoFile table
    f1 = RepoFile(id="f1", repo_id=repo.id, path="main.py", language="python", size=100, content_hash="h1")
    f2 = RepoFile(id="f2", repo_id=repo.id, path="requirements.txt", language="pip", size=50, content_hash="h2")
    db_session.add_all([f1, f2])
    db_session.commit()

    yaml_str = generate_default_ci_workflow(repo, db_session, use_ai=False)

    assert _validate_workflow_yaml(yaml_str)
    assert "name: CodeBrain CI" in yaml_str
    assert "workflow_dispatch:" in yaml_str
    assert "contents: write" in yaml_str
    assert "actions/checkout@v4" in yaml_str
    assert "actions/setup-python@v5" in yaml_str
    assert "pytest" in yaml_str
    # Verify no || true masking
    assert "|| true" not in yaml_str


def test_failure_classification():
    """Verify classification of fixable code issues vs unfixable credential blockers."""
    # 1. Unfixable credential error
    cred_log = "Error: Resource not accessible by integration (HTTP 403 Forbidden)"
    cat1, is_fixable1, expl1 = classify_failure_logs(cred_log)
    assert not is_fixable1
    assert cat1 == "permission_denied"

    # 2. Unfixable missing secret
    secret_log = "Fatal: Secret NPM_TOKEN is not defined in environment"
    cat2, is_fixable2, _ = classify_failure_logs(secret_log)
    assert not is_fixable2
    assert cat2 == "missing_secret"

    # 3. Fixable test failure
    test_log = "FAILED tests/test_api.py::test_login - AssertionError: assert 401 == 200"
    cat3, is_fixable3, _ = classify_failure_logs(test_log)
    assert is_fixable3
    assert cat3 == "test_failure"

    # 4. Fixable syntax error
    syntax_log = "SyntaxError: invalid syntax on line 42"
    cat4, is_fixable4, _ = classify_failure_logs(syntax_log)
    assert is_fixable4
    assert cat4 == "syntax_error"


def test_failure_fingerprint_and_loop_prevention():
    """Verify deterministic failure fingerprinting across timestamps."""
    log_a = "2026-10-12T01:30:00.123Z FAILED tests/test_user.py - AssertionError at 0x7ffd1234"
    log_b = "2026-10-12T01:35:00.999Z FAILED tests/test_user.py - AssertionError at 0x7ffd9876"

    fp_a = compute_failure_fingerprint("test-job", "Run pytest", log_a)
    fp_b = compute_failure_fingerprint("test-job", "Run pytest", log_b)

    assert fp_a == fp_b


def test_deployment_detection(db_session, test_user):
    """Verify deployment manifest detection for Vercel, Render, and Docker."""
    repo = Repo(id="repo-deploy", user_id=test_user.id, name="fullstack-app", source_type="github")
    db_session.add(repo)
    db_session.commit()

    # Add vercel.json
    f_vercel = RepoFile(id="fv", repo_id=repo.id, path="vercel.json", language="json", size=40, content_hash="hv")
    db_session.add(f_vercel)
    db_session.commit()

    deploy_res = detect_repository_deployment(repo, db_session)
    assert deploy_res["is_configured"] is True
    assert deploy_res["provider"] == "vercel"
    assert "vercel.json" in deploy_res["detected_files"][0]
    assert "safety_gates" in deploy_res
    assert len(deploy_res["safety_gates"]) == 5
    assert deploy_res["can_manual_deploy"] is True


def test_user_email_fallback_property(test_user):
    """Ensure User.email property returns a valid email without raising AttributeError."""
    assert test_user.email is not None
    assert "developer@users.noreply.github.com" in test_user.email


def test_extract_owner_repo_pr_and_azure():
    """Verify robust URL parsing separating PR paths and rejecting Azure DevOps."""
    from gitops.pr_client import _extract_owner_repo, extract_pr_number_from_url, UnsupportedProviderError

    assert _extract_owner_repo("org/repo") == ("org", "repo")
    assert _extract_owner_repo("https://github.com/org/repo") == ("org", "repo")
    assert _extract_owner_repo("https://github.com/org/repo/pull/123") == ("org", "repo")
    assert extract_pr_number_from_url("https://github.com/org/repo/pull/123") == 123
    assert _extract_owner_repo("git@github.com:org/repo.git") == ("org", "repo")

    with pytest.raises(UnsupportedProviderError):
        _extract_owner_repo("https://dev.azure.com/myorg/myproj/_git/myrepo/pullrequest/789")


def test_install_ci_workflow_direct_signatures(db_session, test_user, monkeypatch):
    """
    Ensure install_ci_workflow_direct accepts both workflow_content and yaml_content
    keyword arguments without throwing TypeError.
    """
    from automation.ci_setup import install_ci_workflow_direct

    repo = Repo(id="repo-direct", user_id=test_user.id, name="test-repo", source_type="github")
    db_session.add(repo)
    db_session.commit()

    valid_yaml = "name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo OK\n"

    # Mock remote commit to GitHub API
    monkeypatch.setattr("automation.ci_setup.get_user_github_token", lambda u: "gh_test_token")
    monkeypatch.setattr("automation.ci_setup.get_repo_full_name", lambda r: "owner/repo")
    monkeypatch.setattr("automation.ci_setup.get_remote_default_branch", lambda r, token: "main")
    monkeypatch.setattr(
        "automation.ci_setup.create_or_update_remote_file",
        lambda repo_full_name, path, content, commit_message, branch, token: {
            "status": "success",
            "commit_sha": "abc12345",
            "commit_url": "https://github.com/owner/repo/commit/abc12345",
            "file_path": path,
            "branch": branch,
        }
    )

    # 1. Call with workflow_content
    res1 = install_ci_workflow_direct(repo, db_session, test_user, workflow_content=valid_yaml)
    assert res1["success"] is True
    assert res1["commit_sha"] == "abc12345"

    # 2. Call with yaml_content
    res2 = install_ci_workflow_direct(repo, db_session, test_user, yaml_content=valid_yaml)
    assert res2["success"] is True
    assert res2["commit_sha"] == "abc12345"


def test_full_stack_ci_workflow_generation(db_session, test_user):
    """
    Verify that a repository containing both frontend and backend directories/files
    generates a workflow covering both frontend-checks and backend-checks.
    """
    repo = Repo(id="repo-fullstack", user_id=test_user.id, name="fullstack-app", source_type="github")
    db_session.add(repo)
    db_session.commit()

    # Add frontend and backend files
    f_fe_pkg = RepoFile(id="fe1", repo_id=repo.id, path="frontend/package.json", language="json", size=200, content_hash="hfe1")
    f_fe_lock = RepoFile(id="fe2", repo_id=repo.id, path="frontend/package-lock.json", language="json", size=500, content_hash="hfe2")
    f_be_req = RepoFile(id="be1", repo_id=repo.id, path="backend/requirements.txt", language="pip", size=100, content_hash="hbe1")
    f_be_test = RepoFile(id="be2", repo_id=repo.id, path="backend/test_app.py", language="python", size=150, content_hash="hbe2")

    db_session.add_all([f_fe_pkg, f_fe_lock, f_be_req, f_be_test])
    db_session.commit()

    ev = analyze_repository_evidence(repo, db_session)
    assert ev["has_node"] is True
    assert ev["has_python"] is True
    assert len(ev["components"]) >= 2
    assert any("front" in c["name"].lower() for c in ev["components"])
    assert any("back" in c["name"].lower() for c in ev["components"])

    workflow_yaml = generate_default_ci_workflow(repo, db_session, use_ai=False)
    assert "frontend-checks:" in workflow_yaml
    assert "backend-checks:" in workflow_yaml
    assert "actions/setup-node@v4" in workflow_yaml
    assert "actions/setup-python@v5" in workflow_yaml

