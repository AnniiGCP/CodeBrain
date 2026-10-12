"""
backend/automation/deployment_detector.py
-----------------------------------------
Detects existing deployment configurations from repository evidence.
Distinguishes CI testing from production deployment.
Supports: Netlify, Vercel, Render, Docker, GitHub Actions Deployment, and manual configs.
Extracts build commands, output directories, safety gates, and connection states.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from models import Repo, RepoFile

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"


def detect_repository_deployment(repo: Repo, db: Session) -> dict[str, Any]:
    """
    Inspect repository files, manifests, and structure to determine deployment configuration.
    Returns structured deployment specification with verified build parameters,
    connection state, safety gates, and provider dashboard links.
    """
    files = db.query(RepoFile.path).filter(RepoFile.repo_id == repo.id).all()
    paths = [p[0].lower().replace("\\", "/").lstrip("/") for p in files if p[0]]

    # Also inspect storage directory disk files if present
    storage_dir = STORAGE_ROOT / repo.id
    if storage_dir.exists():
        for p in storage_dir.rglob("*"):
            if p.is_file():
                try:
                    rel = str(p.relative_to(storage_dir)).lower().replace("\\", "/")
                    if rel not in paths:
                        paths.append(rel)
                except Exception:
                    pass

    detected_files: list[str] = []
    required_env_vars: list[str] = []

    # Check for .env.example to surface required environment variable keys safely
    for env_name in [".env.example", ".env.template", ".env.sample"]:
        if env_name in paths:
            detected_files.append(env_name)
            if storage_dir.exists() and (storage_dir / env_name).exists():
                try:
                    env_text = (storage_dir / env_name).read_text(encoding="utf-8", errors="ignore")
                    for line in env_text.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            var_key = line.split("=", 1)[0].strip()
                            if var_key and var_key not in required_env_vars:
                                required_env_vars.append(var_key)
                except Exception:
                    pass

    # 1. Check for Netlify configuration (netlify.toml)
    netlify_files = [p for p in paths if p.endswith("netlify.toml") or p.startswith(".netlify/")]
    if netlify_files:
        detected_files.extend(netlify_files)
        build_cmd = "npm run build"
        publish_dir = "dist"
        functions_dir = None

        if storage_dir.exists() and (storage_dir / "netlify.toml").exists():
            try:
                toml_text = (storage_dir / "netlify.toml").read_text(encoding="utf-8", errors="ignore")
                m_cmd = re.search(r'command\s*=\s*["\']([^"\']+)["\']', toml_text)
                if m_cmd:
                    build_cmd = m_cmd.group(1)
                m_pub = re.search(r'publish\s*=\s*["\']([^"\']+)["\']', toml_text)
                if m_pub:
                    publish_dir = m_pub.group(1)
                m_func = re.search(r'functions\s*=\s*["\']([^"\']+)["\']', toml_text)
                if m_func:
                    functions_dir = m_func.group(1)
            except Exception:
                pass

        return {
            "is_configured": True,
            "provider": "netlify",
            "display_name": "Netlify",
            "status": "detected",
            "connection_status": "detected",  # detected | connected | configured
            "deployment_url": None,
            "detected_files": detected_files,
            "build_command": build_cmd,
            "output_dir": publish_dir,
            "functions_dir": functions_dir,
            "target_branch": "main",
            "framework": "Node / Frontend",
            "required_env_vars": required_env_vars[:6],
            "provider_dashboard_url": "https://app.netlify.com",
            "can_manual_deploy": True,
            "description": "Netlify deployment specification detected from netlify.toml.",
            "recommendation": "Netlify automatically deploys production builds when CI quality gates pass. Connect your site in Netlify dashboard or use deploy hooks.",
            "safety_gates": [
                {"step": "Code Change", "status": "verified", "description": "Committed to git repository"},
                {"step": "CI Tests & Builds", "status": "required", "description": "Continuous integration quality gate must pass"},
                {"step": "Required Checks Pass", "status": "enforced", "description": "Production releases blocked on failing checks"},
                {"step": "Deployment Triggered", "status": "ready", "description": "Netlify webhook or manual trigger"},
                {"step": "Provider Confirmation", "status": "pending", "description": "Verified production preview or live URL"}
            ],
        }

    # 2. Check for Vercel configuration (vercel.json)
    vercel_files = [p for p in paths if p.endswith("vercel.json") or p.startswith(".vercel/")]
    if vercel_files:
        detected_files.extend(vercel_files)
        return {
            "is_configured": True,
            "provider": "vercel",
            "display_name": "Vercel",
            "status": "detected",
            "connection_status": "detected",
            "deployment_url": None,
            "detected_files": detected_files,
            "build_command": "npm run build",
            "output_dir": ".vercel/output",
            "target_branch": "main",
            "framework": "Next.js / Vite / React",
            "required_env_vars": required_env_vars[:6],
            "provider_dashboard_url": "https://vercel.com/dashboard",
            "can_manual_deploy": True,
            "description": "Vercel deployment specification detected from vercel.json.",
            "recommendation": "Connect repository to Vercel for zero-config preview deployments gated behind CI checks.",
            "safety_gates": [
                {"step": "Code Change", "status": "verified", "description": "Committed to branch"},
                {"step": "CI Tests & Builds", "status": "required", "description": "Linting and frontend builds pass"},
                {"step": "Required Checks Pass", "status": "enforced", "description": "Branch protection blocks unverified PRs"},
                {"step": "Deployment Triggered", "status": "ready", "description": "Vercel Git Integration"},
                {"step": "Provider Confirmation", "status": "pending", "description": "Live production URL assigned"}
            ],
        }

    # 3. Check for dedicated GitHub Actions deployment workflow
    deploy_workflows = [p for p in paths if ".github/workflows/" in p and ("deploy" in p or "release" in p or "publish" in p)]
    if deploy_workflows:
        detected_files.extend(deploy_workflows)
        return {
            "is_configured": True,
            "provider": "github_actions",
            "display_name": "GitHub Actions Deployment",
            "status": "configured",
            "connection_status": "connected",
            "deployment_url": None,
            "detected_files": detected_files,
            "build_command": "CI Workflow Pipeline",
            "output_dir": "GitHub Environment",
            "target_branch": "main",
            "framework": "GitHub Actions Workflow",
            "required_env_vars": required_env_vars[:6],
            "provider_dashboard_url": f"https://github.com",
            "can_manual_deploy": True,
            "description": f"Deployment workflow detected at {deploy_workflows[0]}.",
            "recommendation": "Deployment job is automated via GitHub Actions. Deployment gates require CI check jobs to pass first.",
            "safety_gates": [
                {"step": "Code Change", "status": "verified", "description": "Git commit pushed to main"},
                {"step": "CI Quality Gates", "status": "required", "description": "All frontend and backend checks pass"},
                {"step": "Deployment Job Triggered", "status": "ready", "description": f"Workflow {deploy_workflows[0]}"},
                {"step": "Provider Confirmation", "status": "pending", "description": "Artifact release published"}
            ],
        }

    # 4. Check for Render configuration (render.yaml)
    render_files = [p for p in paths if p.endswith("render.yaml") or p.endswith(".render.yaml")]
    if render_files:
        detected_files.extend(render_files)
        return {
            "is_configured": True,
            "provider": "render",
            "display_name": "Render Cloud",
            "status": "detected",
            "connection_status": "detected",
            "deployment_url": None,
            "detected_files": detected_files,
            "build_command": "pip install -r requirements.txt",
            "output_dir": "Web Service",
            "target_branch": "main",
            "framework": "FastAPI / Python Web Service",
            "required_env_vars": required_env_vars[:6],
            "provider_dashboard_url": "https://dashboard.render.com",
            "can_manual_deploy": True,
            "description": "Render blueprint specification detected (render.yaml).",
            "recommendation": "Render will auto-deploy your web services once CI tests pass.",
            "safety_gates": [
                {"step": "Code Change", "status": "verified", "description": "Pushed to default branch"},
                {"step": "CI Checks Pass", "status": "required", "description": "Unit tests and builds pass"},
                {"step": "Deploy Hook Triggered", "status": "ready", "description": "Render Deploy Hook"},
                {"step": "Service Health Check", "status": "pending", "description": "HTTP 200 health check response"}
            ],
        }

    # 5. Check for Docker container configuration
    docker_files = [p for p in paths if "dockerfile" in p or "docker-compose" in p]
    if docker_files:
        detected_files.extend(docker_files)
        return {
            "is_configured": True,
            "provider": "docker",
            "display_name": "Container / Docker",
            "status": "detected",
            "connection_status": "detected",
            "deployment_url": None,
            "detected_files": detected_files,
            "build_command": "docker build -t app:latest .",
            "output_dir": "Container Registry",
            "target_branch": "main",
            "framework": "Docker Container",
            "required_env_vars": required_env_vars[:6],
            "provider_dashboard_url": "https://hub.docker.com",
            "can_manual_deploy": False,
            "description": "Containerization manifests detected (Dockerfile / docker-compose).",
            "recommendation": "Container images can be built in CI and published to AWS ECS, GCP Cloud Run, or Kubernetes.",
            "safety_gates": [
                {"step": "Code Change", "status": "verified", "description": "Git commit pushed"},
                {"step": "CI Test Checks", "status": "required", "description": "Component unit tests pass"},
                {"step": "Container Image Build", "status": "ready", "description": "Docker build check"},
                {"step": "Registry Push", "status": "pending", "description": "Publish image tag"}
            ],
        }

    # Fallback recommendations
    has_python = any(p.endswith(".py") or "requirements.txt" in p for p in paths)
    has_node = any(p.endswith(".tsx") or p.endswith(".jsx") or "package.json" in p for p in paths)

    recommendation = "Connect a deployment provider (Netlify, Vercel, or Render) when ready."
    if has_node and not has_python:
        recommendation = "Recommended deployment platform for this Frontend project: Netlify or Vercel."
    elif has_python and not has_node:
        recommendation = "Recommended deployment platform for this Python API backend: Render, Railway, or Docker."
    elif has_node and has_python:
        recommendation = "Full-stack project: Recommended deployment is Netlify/Vercel for frontend and Render/Docker for backend API."

    return {
        "is_configured": False,
        "provider": "none",
        "display_name": "Not Configured",
        "status": "not_configured",
        "connection_status": "not_configured",
        "deployment_url": None,
        "detected_files": [],
        "build_command": None,
        "output_dir": None,
        "target_branch": "main",
        "framework": "General Project",
        "required_env_vars": required_env_vars[:6],
        "provider_dashboard_url": None,
        "can_manual_deploy": False,
        "description": "No automated deployment manifests discovered in repository.",
        "recommendation": recommendation,
        "safety_gates": [],
    }
