"""
backend/tests/test_full_stack_ci_detection.py
---------------------------------------------
Tests for repository-wide component discovery (Frontend, Backend API, subfolders),
manifest extraction, deployment detection (Netlify, Vercel, Render),
and multi-job workflow synthesis without fake quality gates.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from automation.ci_setup import analyze_repository_evidence, _synthesize_deterministic_workflow, _validate_workflow_yaml
from automation.deployment_detector import detect_repository_deployment
from database import SessionLocal
from models import Repo, User, RepoFile


def test_full_stack_monorepo_evidence_and_workflow():
    db = SessionLocal()
    try:
        # Test on real repository ce0ed015-02c7-448d-8606-e58d386e4490 (kangan289/dev)
        repo = db.query(Repo).filter(Repo.id == "ce0ed015-02c7-448d-8606-e58d386e4490").first()
        if not repo:
            pytest.skip("Test repository ce0ed015-02c7-448d-8606-e58d386e4490 not present in database.")

        evidence = analyze_repository_evidence(repo, db)
        components = evidence.get("components", [])
        assert len(components) >= 2, "Must detect both Frontend and Backend components"

        comp_names = [c["name"] for c in components]
        assert any("front" in n.lower() for n in comp_names), "Frontend UI must be detected"
        assert any("back" in n.lower() or "api" in n.lower() for n in comp_names), "Backend API must be detected"

        # Check frontend details
        front_comp = next(c for c in components if "front" in c["name"].lower())
        assert front_comp["build_command"] == "npm run build"
        assert front_comp["lint_command"] == "npm run lint"

        # Check backend details
        back_comp = next(c for c in components if "back" in c["name"].lower() or "api" in c["name"].lower())
        assert back_comp["path"] == "server"
        assert back_comp["framework"] == "express"
        assert back_comp.get("entry_point") == "server/src/index.js"

        # Check deployment detection
        deployment = detect_repository_deployment(repo, db)
        assert deployment["is_configured"] is True
        assert deployment["provider"] == "netlify"
        assert "netlify.toml" in deployment["detected_files"][0]

        # Check workflow synthesis
        wf_yaml = _synthesize_deterministic_workflow(evidence)
        assert _validate_workflow_yaml(wf_yaml) is True

        parsed = yaml.safe_load(wf_yaml)
        jobs = parsed["jobs"]

        # Must have both frontend and backend quality gates
        assert "frontend-checks" in jobs
        assert "backend-checks" in jobs
        assert "deployment-gate" in jobs

        # Ensure NO fake quality gates
        assert "|| true" not in wf_yaml
        assert "--if-present" not in wf_yaml

        # Deployment gate must depend on both checks
        assert set(jobs["deployment-gate"]["needs"]) == {"frontend-checks", "backend-checks"}

    finally:
        db.close()


def test_python_and_node_monorepo_synthesis():
    mock_evidence = {
        "ecosystems": ["python", "node"],
        "components": [
            {
                "name": "Frontend UI",
                "path": "frontend",
                "ecosystem": "node",
                "framework": "vite/react",
                "runtime_version": "18.x",
                "package_manager": "npm",
                "lockfile": "frontend/package-lock.json",
                "install_command": "npm ci",
                "build_command": "npm run build",
                "lint_command": "npm run lint",
                "test_command": "npm test",
                "has_test_suite": True,
            },
            {
                "name": "Backend API",
                "path": "backend",
                "ecosystem": "python",
                "framework": "fastapi",
                "runtime_version": "3.11",
                "package_manager": "pip",
                "lockfile": "backend/requirements.txt",
                "install_command": "pip install -r backend/requirements.txt",
                "build_command": None,
                "lint_command": "flake8",
                "test_command": "pytest backend/",
                "has_test_suite": True,
            },
        ],
    }

    wf = _synthesize_deterministic_workflow(mock_evidence)
    assert _validate_workflow_yaml(wf) is True

    parsed = yaml.safe_load(wf)
    jobs = parsed["jobs"]
    assert "frontend-checks" in jobs
    assert "backend-checks" in jobs
    assert "deployment-gate" in jobs

    # Frontend steps
    fe_steps = jobs["frontend-checks"]["steps"]
    assert any("npm run build" in s.get("run", "") for s in fe_steps)
    assert any("npm test" in s.get("run", "") for s in fe_steps)

    # Backend steps
    be_steps = jobs["backend-checks"]["steps"]
    assert any("pytest backend/" in s.get("run", "") for s in be_steps)


def test_single_component_honest_test_reporting():
    mock_evidence = {
        "ecosystems": ["node"],
        "components": [
            {
                "name": "Frontend UI",
                "path": ".",
                "ecosystem": "node",
                "framework": "react",
                "runtime_version": "18.x",
                "package_manager": "npm",
                "lockfile": "package-lock.json",
                "install_command": "npm ci",
                "build_command": "npm run build",
                "lint_command": None,
                "test_command": None,
                "has_test_suite": False,
            }
        ],
    }

    wf = _synthesize_deterministic_workflow(mock_evidence)
    assert _validate_workflow_yaml(wf) is True
    parsed = yaml.safe_load(wf)
    # Does not invent fake tests
    steps = parsed["jobs"]["frontend-checks"]["steps"]
    assert not any("npm test" in s.get("run", "") for s in steps)
    assert any("npm run build" in s.get("run", "") for s in steps)
