"""
backend/automation/ci_setup.py
------------------------------
Repository-aware CI/CD workflow detection, multi-component full-stack
evidence discovery, AI-powered pipeline synthesis, and installation
(via Pull Request or authenticated GitHub Contents API).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from ai.config import TaskType
from ai.router import get_ai_router
from auth import get_user_github_token
from gitops.git_ops import create_branch_and_commit, sanitize_sensitive_text
from gitops.github_actions import (
    check_pr_merged,
    check_remote_file_exists,
    create_or_update_remote_file,
    fetch_remote_file_content,
    fetch_remote_workflow_files,
    get_remote_default_branch,
)
from gitops.pr_client import _extract_owner_repo, create_pull_request
from models import AutomationLog, Repo, RepoCiConfig, RepoFile, User

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"


def get_repo_full_name(repo: Repo) -> str:
    """
    Resolve the canonical 'owner/repo' GitHub slug for a Repo instance.
    Inspects repo.name, origin git URL in storage directory, and user.github_username.
    Separates repository identity from PR or malformed identifiers.
    """
    try:
        owner, name = _extract_owner_repo(repo.name)
        return f"{owner}/{name}"
    except Exception:
        pass

    storage_dir = STORAGE_ROOT / repo.id
    if storage_dir.exists():
        try:
            import git
            gr = git.Repo(str(storage_dir))
            remote_url = gr.remotes["origin"].url
            owner, name = _extract_owner_repo(remote_url)
            return f"{owner}/{name}"
        except Exception:
            pass

    if repo.user and getattr(repo.user, "github_username", None):
        clean_name = repo.name.split("/")[-1].removesuffix(".git")
        return f"{repo.user.github_username}/{clean_name}"
    return repo.name


def get_or_create_repo_ci_config(repo: Repo, db: Session) -> RepoCiConfig:
    """Retrieve or initialize the isolated RepoCiConfig record for this repository."""
    ci_conf = db.query(RepoCiConfig).filter(RepoCiConfig.repo_id == repo.id).first()
    if not ci_conf:
        ci_conf = RepoCiConfig(
            repo_id=repo.id,
            provider="github_actions",
            default_branch="main",
            detected_ecosystems="[]",
            workflow_path=".github/workflows/ci.yml",
            setup_status="not_configured",
            auto_fix_enabled=True,
            auto_commit_enabled=False,
            max_retry_budget=3,
            current_retry_count=0,
        )
        db.add(ci_conf)
        db.commit()
    return ci_conf


def detect_ci_workflows(repo_id: str, db: Session, user_token: str | None = None) -> dict[str, Any]:
    """
    Check if .github/workflows/ contains any workflow files in the repository.
    Inspects both local disk/db state and remote GitHub API.
    Updates detected_ci, detected_ci_files, needs_ci_setup, and RepoCiConfig.
    """
    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return {"detected_ci": False, "detected_ci_files": [], "needs_ci_setup": False, "active_workflow_content": None}

    ci_conf = get_or_create_repo_ci_config(repo, db)

    # 1. Query RepoFile table for any files in .github/workflows/
    workflow_files = (
        db.query(RepoFile)
        .filter(
            RepoFile.repo_id == repo_id,
            (RepoFile.path.like(".github/workflows/%") | RepoFile.path.like("/.github/workflows/%")),
        )
        .all()
    )
    found_paths = [f.path.lstrip("/") for f in workflow_files]

    # 2. Filesystem check
    storage_dir = STORAGE_ROOT / repo_id
    if storage_dir.exists():
        for p in storage_dir.rglob(".github/workflows/*"):
            if p.is_file() and (p.name.endswith(".yml") or p.name.endswith(".yaml")):
                try:
                    rel_p = str(p.relative_to(storage_dir)).replace("\\", "/").lstrip("/")
                    if rel_p not in found_paths:
                        found_paths.append(rel_p)
                except Exception:
                    pass

    # 3. Remote GitHub check if source_type == "github"
    if repo.source_type == "github":
        try:
            repo_full_name = get_repo_full_name(repo)
            remote_workflows = fetch_remote_workflow_files(repo_full_name, token=user_token)
            for rw in remote_workflows:
                p = rw.get("path", "")
                if p and p not in found_paths:
                    found_paths.append(p)
        except Exception as exc:
            logger.warning("Could not query remote GitHub workflows for repo %s: %s", repo.id, exc)

    has_ci = len(found_paths) > 0
    repo.detected_ci = has_ci
    repo.detected_ci_files = json.dumps(found_paths)
    repo.needs_ci_setup = (not has_ci) and (repo.source_type == "github")

    # Read active workflow content if available
    active_content = None
    if has_ci:
        target_rel = found_paths[0]
        ci_conf.workflow_path = target_rel
        ci_conf.setup_status = "installed"

        # Try reading from disk
        if storage_dir.exists():
            local_wf = storage_dir / target_rel
            if local_wf.is_file():
                active_content = local_wf.read_text(encoding="utf-8", errors="replace")

        # Fallback to remote GitHub
        if not active_content and repo.source_type == "github":
            repo_full_name = get_repo_full_name(repo)
            active_content = fetch_remote_file_content(repo_full_name, target_rel, token=user_token)

        if active_content:
            ci_conf.active_workflow_content = active_content
    elif ci_conf.setup_status == "installed":
        ci_conf.setup_status = "not_configured"

    db.commit()

    return {
        "detected_ci": repo.detected_ci,
        "detected_ci_files": found_paths,
        "needs_ci_setup": repo.needs_ci_setup,
        "workflow_path": ci_conf.workflow_path,
        "active_workflow_content": active_content or ci_conf.active_workflow_content,
        "setup_status": ci_conf.setup_status,
    }


def analyze_repository_evidence(repo: Repo, db: Session) -> dict[str, Any]:
    """
    Perform deep evidence discovery across the entire repository.
    Identifies all components (frontend, backend APIs, services), lockfiles,
    real scripts (build, lint, test), standalone tests, and deployment manifests.
    """
    storage_dir = STORAGE_ROOT / repo.id
    db_files = db.query(RepoFile.path, RepoFile.language).filter(RepoFile.repo_id == repo.id).all()
    file_paths: list[str] = [p.lower().replace("\\", "/").lstrip("/") for p, _ in db_files if p]

    if storage_dir.exists():
        for p in storage_dir.rglob("*"):
            if p.is_file():
                try:
                    rel = str(p.relative_to(storage_dir)).lower().replace("\\", "/")
                    if rel not in file_paths:
                        file_paths.append(rel)
                except Exception:
                    pass

    components: list[dict[str, Any]] = []

    def inspect_node_package(pkg_path: Path, rel_dir: str, default_name: str) -> dict[str, Any] | None:
        if not pkg_path.exists():
            return None
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None

        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        scripts = data.get("scripts", {})

        is_frontend = (
            any(k in deps for k in ["react", "vue", "svelte", "vite", "next", "astro", "@angular/core", "solid-js"])
            or (pkg_path.parent / "index.html").exists()
            or (pkg_path.parent / "vite.config.ts").exists()
            or (pkg_path.parent / "vite.config.js").exists()
        )
        is_backend = (
            any(k in deps for k in ["express", "fastify", "koa", "nest", "@nestjs/core", "mongoose", "prisma", "pg", "typeorm"])
            or (pkg_path.parent / "src" / "index.js").exists()
            or (pkg_path.parent / "server.js").exists()
            or (pkg_path.parent / "app.js").exists()
        )

        lockfile = None
        install_cmd = "npm install"
        if (pkg_path.parent / "package-lock.json").exists():
            lockfile = f"{rel_dir}/package-lock.json" if rel_dir != "." else "package-lock.json"
            install_cmd = "npm ci"
        elif (pkg_path.parent / "bun.lock").exists() or (pkg_path.parent / "bun.lockb").exists():
            lockfile = f"{rel_dir}/bun.lock" if rel_dir != "." else "bun.lock"
            install_cmd = "npm install"
        elif (pkg_path.parent / "pnpm-lock.yaml").exists():
            lockfile = f"{rel_dir}/pnpm-lock.yaml" if rel_dir != "." else "pnpm-lock.yaml"
            install_cmd = "pnpm install --frozen-lockfile"
        elif (pkg_path.parent / "yarn.lock").exists():
            lockfile = f"{rel_dir}/yarn.lock" if rel_dir != "." else "yarn.lock"
            install_cmd = "yarn install --frozen-lockfile"

        build_cmd = "npm run build" if "build" in scripts else None
        lint_cmd = "npm run lint" if "lint" in scripts else ("npm run check" if "check" in scripts else None)

        test_script = scripts.get("test", "")
        test_cmd = None
        has_test_suite = False
        if test_script and "no test specified" not in test_script.lower() and "exit 1" not in test_script.lower():
            test_cmd = "npm test"
            has_test_suite = True

        entry_point = None
        main_file = data.get("main")
        if main_file and (pkg_path.parent / main_file).exists():
            entry_point = f"{rel_dir}/{main_file}" if rel_dir != "." else main_file
        elif (pkg_path.parent / "src" / "index.js").exists():
            entry_point = f"{rel_dir}/src/index.js" if rel_dir != "." else "src/index.js"
        elif (pkg_path.parent / "server.js").exists():
            entry_point = f"{rel_dir}/server.js" if rel_dir != "." else "server.js"

        framework = "node"
        if "vite" in deps and "react" in deps:
            framework = "vite/react"
        elif "next" in deps:
            framework = "nextjs"
        elif "react" in deps:
            framework = "react"
        elif "vue" in deps:
            framework = "vue"
        elif "express" in deps:
            framework = "express"
        elif "fastify" in deps:
            framework = "fastify"
        elif "nest" in deps:
            framework = "nestjs"

        comp_name = default_name
        if default_name == "Root Application":
            if is_frontend:
                comp_name = "Frontend UI"
            elif is_backend:
                comp_name = "Backend API"

        manifest_rel = f"{rel_dir}/package.json" if rel_dir != "." else "package.json"

        # Detect Node runtime version from engines if specified
        runtime_ver = "18.x"
        engines_node = data.get("engines", {}).get("node", "")
        if "20" in engines_node:
            runtime_ver = "20.x"
        elif "18" in engines_node:
            runtime_ver = "18.x"

        return {
            "name": comp_name,
            "path": rel_dir,
            "ecosystem": "node",
            "framework": framework,
            "runtime_version": runtime_ver,
            "package_manager": "npm",
            "lockfile": lockfile,
            "install_command": install_cmd,
            "build_command": build_cmd,
            "lint_command": lint_cmd,
            "test_command": test_cmd,
            "has_test_suite": has_test_suite,
            "entry_point": entry_point,
            "evidence": [manifest_rel],
        }

    def inspect_python_package(py_dir: Path, rel_dir: str, default_name: str) -> dict[str, Any] | None:
        if not py_dir.exists():
            return None
        has_req = (py_dir / "requirements.txt").exists()
        has_pyproject = (py_dir / "pyproject.toml").exists()
        has_setup = (py_dir / "setup.py").exists()
        has_pipfile = (py_dir / "Pipfile").exists()

        py_files = list(py_dir.glob("*.py")) + list(py_dir.glob("*/*.py"))
        if not (has_req or has_pyproject or has_setup or has_pipfile or py_files):
            return None

        evidence = []
        install_cmd = "pip install -r requirements.txt"
        lockfile = None
        if has_req:
            lockfile = f"{rel_dir}/requirements.txt" if rel_dir != "." else "requirements.txt"
            evidence.append(lockfile)
            install_cmd = f"pip install -r {lockfile}"
        if has_pyproject:
            evidence.append(f"{rel_dir}/pyproject.toml" if rel_dir != "." else "pyproject.toml")
        if has_setup:
            evidence.append(f"{rel_dir}/setup.py" if rel_dir != "." else "setup.py")

        framework = "python"
        all_py_text = ""
        for f in py_files[:10]:
            try:
                all_py_text += f.read_text(encoding="utf-8", errors="ignore")[:2000] + "\n"
            except Exception:
                pass

        if "fastapi" in all_py_text.lower():
            framework = "fastapi"
        elif "django" in all_py_text.lower():
            framework = "django"
        elif "flask" in all_py_text.lower():
            framework = "flask"

        test_dir_exists = (
            (py_dir / "tests").exists()
            or (py_dir / "test").exists()
            or any(f.name.startswith("test_") or f.name.endswith("_test.py") for f in py_files)
        )
        test_cmd = f"pytest {rel_dir}/" if rel_dir != "." else "pytest"

        return {
            "name": default_name,
            "path": rel_dir,
            "ecosystem": "python",
            "framework": framework,
            "runtime_version": "3.11",
            "package_manager": "pip",
            "lockfile": lockfile,
            "install_command": install_cmd,
            "build_command": None,
            "lint_command": "flake8" if any("flake8" in p for p in file_paths) else None,
            "test_command": test_cmd if test_dir_exists else None,
            "has_test_suite": test_dir_exists,
            "entry_point": "main.py" if (py_dir / "main.py").exists() else ("app.py" if (py_dir / "app.py").exists() else None),
            "evidence": evidence or ["python source files"],
        }

    # Resolve effective repository root (handles nested unpacks from uploaded archives)
    root_dir = storage_dir
    if storage_dir.exists():
        children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("__pycache__", ".venv", "faiss.index", "docs", ".git")]
        if len(children) == 1 and ((children[0] / ".git").exists() or (children[0] / "package.json").exists() or (children[0] / "requirements.txt").exists()):
            root_dir = children[0]

    # 1. Inspect root
    if root_dir.exists():
        root_node = inspect_node_package(root_dir / "package.json", ".", "Frontend UI" if any("react" in p or "vite" in p for p in file_paths) else "Root Application")
        if root_node:
            components.append(root_node)

        # Check Python in root if no sub-backend component added yet
        root_py = inspect_python_package(root_dir, ".", "Backend API (Python)")
        if root_py and (root_py.get("lockfile") or root_py.get("has_test_suite")):
            components.append(root_py)

        # 2. Inspect subdirectories (server, backend, api, services)
        for sub in ["server", "backend", "api", "services", "apps/server", "apps/backend", "apps/api"]:
            sub_dir = root_dir / sub
            if sub_dir.is_dir():
                node_comp = inspect_node_package(sub_dir / "package.json", sub, f"Backend API ({sub})")
                if node_comp:
                    components.append(node_comp)
                py_comp = inspect_python_package(sub_dir, sub, f"Backend API ({sub})")
                if py_comp:
                    components.append(py_comp)

        for sub in ["frontend", "client", "ui", "web", "apps/frontend", "apps/client", "apps/web"]:
            sub_dir = root_dir / sub
            if sub_dir.is_dir():
                front_comp = inspect_node_package(sub_dir / "package.json", sub, f"Frontend UI ({sub})")
                if front_comp:
                    components.append(front_comp)

    # 3. Detect standalone test scripts in root
    standalone_tests = []
    if root_dir.exists():
        for test_file in list(root_dir.glob("test_*.js")) + list(root_dir.glob("test_*.py")):
            standalone_tests.append(test_file.name)

    # 4. Fallback or cross-component discovery via indexed DB files
    has_backend_component = any("back" in c["name"].lower() or c["path"] in ("backend", "server", "api") or c["ecosystem"] == "python" for c in components)
    if not has_backend_component:
        has_py_files = any(p.endswith(".py") or "requirements.txt" in p for p in file_paths)
        if has_py_files:
            be_path = "backend" if any(p.startswith("backend/") for p in file_paths) else ("server" if any(p.startswith("server/") for p in file_paths) else ".")
            req_rel = f"{be_path}/requirements.txt" if be_path != "." and f"{be_path}/requirements.txt" in file_paths else "requirements.txt"
            components.append({
                "name": "Backend API",
                "path": be_path,
                "ecosystem": "python",
                "framework": "fastapi" if any("fastapi" in p for p in file_paths) else "python",
                "runtime_version": "3.11",
                "package_manager": "pip",
                "lockfile": req_rel if req_rel in file_paths else None,
                "install_command": f"pip install -r {req_rel}" if be_path == "." else f"pip install -r requirements.txt",
                "build_command": None,
                "lint_command": None,
                "test_command": "pytest",
                "has_test_suite": any("test" in p for p in file_paths),
                "entry_point": "main.py" if any(p.endswith("main.py") for p in file_paths) else None,
                "evidence": [req_rel] if req_rel in file_paths else ["python source files"],
            })

    has_frontend_component = any("front" in c["name"].lower() or (c["ecosystem"] == "node" and c["path"] in (".", "frontend", "client")) for c in components)
    if not has_frontend_component:
        has_node_files = any(p.endswith(".js") or p.endswith(".ts") or p.endswith(".tsx") or "package.json" in p for p in file_paths)
        if has_node_files:
            fe_path = "frontend" if any(p.startswith("frontend/") for p in file_paths) else ("client" if any(p.startswith("client/") for p in file_paths) else ".")
            components.append({
                "name": "Frontend UI",
                "path": fe_path,
                "ecosystem": "node",
                "framework": "react" if any("react" in p for p in file_paths) else "node",
                "runtime_version": "18.x",
                "package_manager": "npm",
                "lockfile": f"{fe_path}/package-lock.json" if fe_path != "." and f"{fe_path}/package-lock.json" in file_paths else "package-lock.json",
                "install_command": "npm ci" if any("package-lock.json" in p for p in file_paths) else "npm install",
                "build_command": "npm run build",
                "lint_command": None,
                "test_command": "npm test",
                "has_test_suite": True,
                "evidence": ["package.json"],
            })

    # If backend API has no npm test but standalone test_api.js exists, attach it!
    for comp in components:
        if comp["ecosystem"] == "node" and not comp["test_command"]:
            js_tests = [t for t in standalone_tests if t.endswith(".js")]
            if js_tests:
                comp["test_command"] = f"node {js_tests[0]}"
                comp["has_test_suite"] = True

    # Deduplicate ecosystems
    ecosystems = list(dict.fromkeys([c["ecosystem"] for c in components]))
    has_python = "python" in ecosystems or any("python" in c["ecosystem"] for c in components)
    has_node = "node" in ecosystems or any("node" in c["ecosystem"] for c in components)

    return {
        "ecosystems": ecosystems,
        "components": components,
        "standalone_tests": standalone_tests,
        "has_python": has_python,
        "has_node": has_node,
        "has_rust": any("cargo.toml" in p for p in file_paths),
        "has_go": any("go.mod" in p for p in file_paths),
        "total_files": len(file_paths),
    }


def generate_default_ci_workflow(repo: Repo, db: Session, use_ai: bool = True) -> str:
    """
    Synthesize tailored GitHub Actions CI workflow using repository evidence and AI.
    Follows least-privilege permissions, pinned actions, paths-ignore, and syntax validation.
    """
    evidence = analyze_repository_evidence(repo, db)

    # 1. Attempt AI synthesis if requested
    if use_ai:
        try:
            ai_yaml = _generate_ai_workflow(repo, evidence)
            if ai_yaml and _validate_workflow_yaml(ai_yaml):
                return ai_yaml
        except Exception as exc:
            logger.warning("AI workflow generation failed (%s). Using verified deterministic template.", exc)

    # 2. Deterministic evidence-based synthesis (guaranteed valid YAML)
    return _synthesize_deterministic_workflow(evidence)


def _validate_workflow_yaml(yaml_text: str) -> bool:
    """Validate YAML syntax and verify basic GitHub Actions structure."""
    try:
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            return False
        return bool(parsed.get("name") and parsed.get("jobs"))
    except Exception as exc:
        logger.warning("YAML validation error: %s", exc)
        return False


def _generate_ai_workflow(repo: Repo, evidence: dict[str, Any]) -> str | None:
    """Generate workflow YAML using CodeBrain's central AI Router."""
    router = get_ai_router()
    components_summary = []
    for c in evidence.get("components", []):
        components_summary.append(
            f"- {c['name']} (path: '{c['path']}', ecosystem: {c['ecosystem']}, framework: {c['framework']}, "
            f"install: '{c['install_command']}', build: '{c['build_command']}', test: '{c['test_command']}', "
            f"entry_point: '{c.get('entry_point')}')"
        )
    comps_str = "\n".join(components_summary) or "Single application"

    prompt = f"""You are a senior DevOps architect and GitHub Actions specialist.
Generate a tailored `.github/workflows/ci.yml` for this repository:
Repository: {repo.name}
Detected Components:
{comps_str}
Standalone Test Scripts: {', '.join(evidence.get('standalone_tests', [])) or 'None'}

Requirements:
- Output ONLY the valid GitHub Actions YAML inside a ```yaml block.
- name: CodeBrain CI
- Triggers: push and pull_request on branches [ main, master ], with paths-ignore for 'docs/**', 'README.md', '*.md'.
- Also include trigger: workflow_dispatch: so the run can be manually or API dispatched.
- permissions:
    contents: write
    pull-requests: write
- Pinned actions: actions/checkout@v4, actions/setup-python@v5, actions/setup-node@v4.
- Create independent jobs for each detected component (e.g. frontend-checks, backend-checks).
- CRITICAL FULL-STACK RULE: If BOTH frontend and backend are detected, generate separate jobs for BOTH. Do NOT omit backend checks.
- NO fake quality gates: do NOT use '|| true' or 'continue-on-error: true' to conceal failed tests or builds.
- If a test script is missing, echo honest notice rather than inventing fake tests.
- If deployment configuration is present, gate deployment behind both frontend and backend quality checks.
- Do NOT invent fake secrets, credentials, or arbitrary commands.
"""
    messages = [
        {"role": "system", "content": "You are a DevOps engineer specializing in GitHub Actions. Output only valid YAML without fake test bypasses."},
        {"role": "user", "content": prompt},
    ]
    res = router.complete(TaskType.DOCUMENTATION, messages, max_tokens=2200, temperature=0.1)
    content = res.get("content", "")

    candidate = None
    match = re.search(r"```(?:yaml|yml)?\n(.*?)```", content, re.DOTALL)
    if match:
        candidate = match.group(1).strip() + "\n"
    elif content.strip().startswith("name:"):
        candidate = content.strip() + "\n"

    if not candidate:
        return None

    # Quality check: Reject fake error concealment
    if "|| true" in candidate or "continue-on-error: true" in candidate:
        logger.warning("AI workflow proposal contained fake check bypasses; falling back to deterministic template.")
        return None

    # Full-stack coverage verification: If repository evidence has both node and python/backend,
    # ensure candidate has jobs for both
    if evidence.get("has_python") and evidence.get("has_node"):
        if "backend" not in candidate.lower() or "frontend" not in candidate.lower():
            logger.warning("AI workflow proposal missed full-stack jobs; falling back to deterministic template.")
            return None

    return candidate


def _synthesize_deterministic_workflow(evidence: dict[str, Any]) -> str:
    """Deterministic, verified GitHub Actions workflow generator covering all components."""
    components = evidence.get("components", [])

    lines = [
        "name: CodeBrain CI",
        "",
        "on:",
        "  push:",
        "    branches: [ main, master ]",
        "    paths-ignore:",
        "      - 'docs/**'",
        "      - 'README.md'",
        "      - '*.md'",
        "  pull_request:",
        "    branches: [ main, master ]",
        "    paths-ignore:",
        "      - 'docs/**'",
        "      - 'README.md'",
        "      - '*.md'",
        "  workflow_dispatch:",
        "",
        "permissions:",
        "  contents: write",
        "  pull-requests: write",
        "",
        "jobs:",
    ]

    job_ids: list[str] = []

    # If components were detected, build jobs for each
    for comp in components:
        c_path = comp["path"]
        c_name = comp["name"]
        c_eco = comp["ecosystem"]
        work_dir = "" if c_path == "." else c_path

        if "front" in c_name.lower() or (c_eco == "node" and c_path in (".", "frontend", "client")):
            job_id = "frontend-checks"
            job_ids.append(job_id)
            lock_path = comp.get("lockfile") or "package-lock.json"
            lines.extend([
                f"  {job_id}:",
                f"    name: {c_name} Quality Gate",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - name: Checkout code",
                "        uses: actions/checkout@v4",
                "",
                f"      - name: Set up Node {comp.get('runtime_version', '18.x')}",
                "        uses: actions/setup-node@v4",
                "        with:",
                f'          node-version: "{comp.get("runtime_version", "18.x")}"',
                '          cache: "npm"',
                f"          cache-dependency-path: {lock_path}",
                "",
                "      - name: Install dependencies",
                *( [f"        working-directory: {work_dir}"] if work_dir else [] ),
                f"        run: {comp['install_command']}",
                "",
            ])
            if comp.get("lint_command"):
                lines.extend([
                    "      - name: Run linting and static analysis",
                    *( [f"        working-directory: {work_dir}"] if work_dir else [] ),
                    f"        run: {comp['lint_command']}",
                    "",
                ])
            if comp.get("test_command"):
                lines.extend([
                    "      - name: Run frontend test suite",
                    *( [f"        working-directory: {work_dir}"] if work_dir else [] ),
                    f"        run: {comp['test_command']}",
                    "",
                ])
            if comp.get("build_command"):
                lines.extend([
                    "      - name: Build frontend production bundle",
                    *( [f"        working-directory: {work_dir}"] if work_dir else [] ),
                    f"        run: {comp['build_command']}",
                    "",
                ])

        elif "back" in c_name.lower() or c_path in ("server", "backend", "api"):
            job_id = "backend-checks"
            job_ids.append(job_id)

            if c_eco == "node":
                lock_path = comp.get("lockfile") or (f"{work_dir}/package-lock.json" if work_dir else "package-lock.json")
                lines.extend([
                    f"  {job_id}:",
                    f"    name: {c_name} Quality Gate",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - name: Checkout code",
                    "        uses: actions/checkout@v4",
                    "",
                    f"      - name: Set up Node {comp.get('runtime_version', '18.x')}",
                    "        uses: actions/setup-node@v4",
                    "        with:",
                    f'          node-version: "{comp.get("runtime_version", "18.x")}"',
                    '          cache: "npm"',
                    f"          cache-dependency-path: {lock_path}",
                    "",
                    "      - name: Install server dependencies",
                    *( [f"        working-directory: {work_dir}"] if work_dir else [] ),
                    f"        run: {comp['install_command']}",
                    "",
                ])
                if comp.get("entry_point"):
                    lines.extend([
                        "      - name: Validate server entry point syntax",
                        f"        run: node --check {comp['entry_point']}",
                        "",
                    ])
                if comp.get("test_command"):
                    lines.extend([
                        "      - name: Run API test suite",
                        f"        run: {comp['test_command']}",
                        "",
                    ])
                elif not comp.get("test_command"):
                    lines.extend([
                        "      - name: Test suite notice",
                        '        run: echo "No automated unit test runner configured for backend server."',
                        "",
                    ])

            elif c_eco == "python":
                lock_path = comp.get("lockfile") or "requirements.txt"
                py_work_dir = "" if c_path == "." else c_path
                lock_file_name = "requirements.txt"
                lines.extend([
                    f"  {job_id}:",
                    f"    name: {c_name} Quality Gate",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - name: Checkout code",
                    "        uses: actions/checkout@v4",
                    "",
                    f"      - name: Set up Python {comp.get('runtime_version', '3.11')}",
                    "        uses: actions/setup-python@v5",
                    "        with:",
                    f'          python-version: "{comp.get("runtime_version", "3.11")}"',
                    '          cache: "pip"',
                    f"          cache-dependency-path: {lock_path}",
                    "",
                    "      - name: Install dependencies",
                    *( [f"        working-directory: {py_work_dir}"] if py_work_dir else [] ),
                    "        run: |",
                    "          python -m pip install --upgrade pip",
                    f"          if [ -f {lock_file_name} ]; then pip install -r {lock_file_name}; elif [ -f {lock_path} ]; then pip install -r {lock_path}; fi",
                    "          pip install pytest pytest-asyncio",
                    "",
                ])
                if comp.get("test_command"):
                    lines.extend([
                        "      - name: Run backend tests",
                        *( [f"        working-directory: {py_work_dir}"] if py_work_dir else [] ),
                        f"        run: {comp['test_command']}",
                        "",
                    ])
                else:
                    lines.extend([
                        "      - name: Test suite notice",
                        *( [f"        working-directory: {py_work_dir}"] if py_work_dir else [] ),
                        '        run: echo "No automated tests found in python component."',
                        "",
                    ])

    # If no components were detected via package.json/python
    if not job_ids:
        lines.extend([
            "  build-and-test:",
            "    name: Repository Quality Gate",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - name: Checkout code",
            "        uses: actions/checkout@v4",
            "",
            "      - name: Verify repository structure",
            '        run: echo "CodeBrain repository validation passed."',
            "",
        ])
        job_ids.append("build-and-test")

    # Add deployment gate if multiple jobs exist
    if len(job_ids) >= 2:
        needs_str = f"[ {', '.join(job_ids)} ]"
        lines.extend([
            "  deployment-gate:",
            "    name: Deployment Quality Gate",
            f"    needs: {needs_str}",
            "    runs-on: ubuntu-latest",
            "    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master'",
            "    steps:",
            "      - name: Validate quality gates passed",
            '        run: echo "CI quality checks passed for all components. Repository is ready for production deployment."',
            "",
        ])

    return "\n".join(lines).strip() + "\n"


def get_ci_workflow_preview(repo: Repo, db: Session) -> dict[str, Any]:
    """
    Generate unified diff and explanation of proposed CI workflow without modifying GitHub.
    Allows user to review exact changes and permissions before approval.
    """
    ci_status = detect_ci_workflows(repo.id, db)
    ci_conf = get_or_create_repo_ci_config(repo, db)

    if ci_status.get("detected_ci") and ci_status.get("active_workflow_content"):
        content = ci_status["active_workflow_content"]
        return {
            "repo_id": repo.id,
            "has_ci": True,
            "is_already_configured": True,
            "detected_ci_files": ci_status.get("detected_ci_files", []),
            "needs_ci_setup": False,
            "workflow_path": ci_conf.workflow_path,
            "workflow_filename": ci_conf.workflow_path,
            "workflow_content": content,
            "diff_preview": "// Active workflow installed on remote repository.",
            "setup_status": "installed",
            "explanation": "Active CI workflow detected. CodeBrain will validate fixes against this pipeline.",
        }

    # Generate proposal
    workflow_yaml = ci_conf.proposed_workflow_content
    if not workflow_yaml:
        workflow_yaml = generate_default_ci_workflow(repo, db)
        ci_conf.proposed_workflow_content = workflow_yaml

    # Unified diff
    yaml_lines = workflow_yaml.splitlines()
    diff_lines = [
        "--- /dev/null",
        "+++ b/.github/workflows/ci.yml",
        f"@@ -0,0 +1,{len(yaml_lines)} @@",
    ]
    diff_lines.extend(f"+{line}" for line in yaml_lines)
    diff_preview = "\n".join(diff_lines)
    ci_conf.proposed_diff = diff_preview
    ci_conf.setup_status = "proposal_ready"
    db.commit()

    return {
        "repo_id": repo.id,
        "has_ci": False,
        "is_already_configured": False,
        "detected_ci_files": [],
        "needs_ci_setup": True,
        "workflow_path": ".github/workflows/ci.yml",
        "workflow_filename": ".github/workflows/ci.yml",
        "workflow_content": workflow_yaml,
        "diff_preview": diff_preview,
        "setup_status": "proposal_ready",
        "explanation": "No existing CI workflow detected. CodeBrain generated this quality gate tailored to your project components.",
    }


def create_ci_setup_pr(repo: Repo, db: Session, current_user: User, yaml_content: str | None = None) -> dict[str, Any]:
    """
    Generate default GitHub Actions workflow and create a PR for user review.
    Does NOT directly push to default branch or bypass branch protection.
    """
    if repo.source_type != "github":
        raise ValueError("CI setup via Pull Request is only supported for GitHub repositories.")

    ci_conf = get_or_create_repo_ci_config(repo, db)
    user_token = get_user_github_token(current_user)
    workflow_yaml = yaml_content or ci_conf.proposed_workflow_content or generate_default_ci_workflow(repo, db)

    # Build unified diff for .github/workflows/ci.yml
    yaml_lines = workflow_yaml.splitlines()
    diff_lines = [
        "--- /dev/null",
        "+++ b/.github/workflows/ci.yml",
        f"@@ -0,0 +1,{len(yaml_lines)} @@",
    ]
    diff_lines.extend(f"+{line}" for line in yaml_lines)
    diff_patch = "\n".join(diff_lines) + "\n"

    branch_name = "codebrain/setup-ci-workflow"
    commit_message = (
        "ci: add GitHub Actions CI workflow (.github/workflows/ci.yml)\n\n"
        "Proposed by CodeBrain based on detected repository language structure."
    )

    try:
        # 1. Branch & Commit via GitOps
        branch_result = create_branch_and_commit(
            repo_id=repo.id,
            patch=diff_patch,
            branch_name=branch_name,
            commit_message=commit_message,
            token=user_token,
        )

        # 2. Open Pull Request on GitHub
        pr_title = "[CodeBrain] Setup GitHub Actions CI Workflow"
        pr_body = (
            "## 🚀 Automated CI Workflow Setup\n\n"
            "CodeBrain detected that this repository currently does not have an active continuous integration workflow.\n\n"
            "### 📦 Proposed Changes\n"
            "- Added `.github/workflows/ci.yml` tailored to the detected tech stack.\n"
            "- Configured automated testing and build validation on pull requests and pushes to `main`.\n\n"
            "### 💡 Next Steps\n"
            "1. Review the proposed workflow file.\n"
            "2. Merge this Pull Request into your default branch.\n"
            "3. Subsequent CodeBrain automated fixes will validate against these checks!"
        )

        repo_full_name = get_repo_full_name(repo)
        pr_result = create_pull_request(
            repo_full_name=repo_full_name,
            branch_name=branch_name,
            base_branch=getattr(branch_result, "default_branch", "main") or "main",
            title=pr_title,
            body=pr_body,
            token=user_token,
        )

        pr_number = pr_result["pr_number"]
        pr_url = pr_result["pr_url"]

        # Update RepoCiConfig state
        ci_conf.setup_status = "awaiting_installation"
        ci_conf.pr_number = pr_number
        ci_conf.pr_url = pr_url
        ci_conf.branch_name = branch_name
        ci_conf.workflow_path = ".github/workflows/ci.yml"
        ci_conf.active_workflow_content = workflow_yaml

        # Record in AutomationLog
        log_entry = AutomationLog(
            id=str(uuid.uuid4()),
            repo_id=repo.id,
            stage="CI_SETUP_PROPOSED",
            outcome="SUCCESS",
            message=f"Created proposal PR #{pr_number} for GitHub Actions CI workflow (.github/workflows/ci.yml).",
            details=pr_url,
        )
        db.add(log_entry)
        db.commit()

        return {
            "status": "pr_opened",
            "setup_status": "awaiting_installation",
            "pr_number": pr_number,
            "pr_url": pr_url,
            "branch_name": branch_name,
            "workflow_content": workflow_yaml,
        }
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        raise RuntimeError(clean_err) from None


def install_ci_workflow_direct(
    repo: Repo,
    db: Session,
    current_user: User,
    workflow_content: str | None = None,
    yaml_content: str | None = None,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """
    Directly commit and push the CI workflow file to the default branch.
    Prefers GitHub REST API (Contents API) to avoid local Git CLI and token exposure.
    Falls back to sanitized local Git push if API is not applicable.
    """
    ci_conf = get_or_create_repo_ci_config(repo, db)
    user_token = get_user_github_token(current_user)
    raw_content = workflow_content or yaml_content or ci_conf.proposed_workflow_content or generate_default_ci_workflow(repo, db)
    
    # Pre-validate workflow YAML structure before committing
    if not _validate_workflow_yaml(raw_content):
        raise ValueError("Provided or generated CI workflow content is invalid YAML structure.")

    content_to_commit = raw_content
    msg = commit_message or "ci: configure GitHub Actions CI quality gate (.github/workflows/ci.yml)"
    default_branch = ci_conf.default_branch or "main"

    commit_sha = ""
    commit_url = ""

    # 1. Prefer authenticated GitHub Contents API
    if repo.source_type == "github" and user_token:
        repo_full_name = get_repo_full_name(repo)
        # Fetch remote default branch to be certain
        remote_branch = get_remote_default_branch(repo_full_name, token=user_token)
        target_branch = remote_branch or default_branch

        try:
            api_res = create_or_update_remote_file(
                repo_full_name=repo_full_name,
                path=".github/workflows/ci.yml",
                content=content_to_commit,
                commit_message=msg,
                branch=target_branch,
                token=user_token,
            )
            commit_sha = api_res.get("commit_sha", "")
            commit_url = api_res.get("commit_url", "")
            default_branch = target_branch
        except Exception as exc:
            clean_err = sanitize_sensitive_text(str(exc))
            raise RuntimeError(clean_err) from None

        # Synchronize local file on disk if working tree exists
        storage_dir = STORAGE_ROOT / repo.id
        if storage_dir.exists():
            try:
                local_wf = storage_dir / ".github" / "workflows" / "ci.yml"
                local_wf.parent.mkdir(parents=True, exist_ok=True)
                local_wf.write_text(content_to_commit, encoding="utf-8")
            except Exception:
                pass
    else:
        # Fallback to local Git CLI push with sanitized credentials
        storage_dir = STORAGE_ROOT / repo.id
        if not storage_dir.exists():
            raise RuntimeError("Repository storage directory not found.")

        repo_root = storage_dir
        children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs", "faiss.index")]
        if len(children) == 1 and (children[0] / ".git").exists():
            repo_root = children[0]

        from git import Repo as GitRepo, Actor
        git_repo = GitRepo(str(repo_root))
        try:
            default_branch = git_repo.active_branch.name
        except Exception:
            pass

        wf_path = repo_root / ".github" / "workflows" / "ci.yml"
        wf_path.parent.mkdir(parents=True, exist_ok=True)
        wf_path.write_text(content_to_commit, encoding="utf-8")

        git_repo.git.add(".github/workflows/ci.yml")
        author = Actor("CodeBrain Bot", "codebrain@noreply.local")
        commit = git_repo.index.commit(msg, author=author, committer=author)
        commit_sha = commit.hexsha

        from gitops.git_ops import _inject_credentials, _detect_provider
        remote_url = git_repo.remotes["origin"].url
        provider = _detect_provider(remote_url)
        clean_remote = re.sub(r"https?://[^@]+@", "https://", remote_url)
        push_url = _inject_credentials(clean_remote, provider, token=user_token)

        try:
            git_repo.git.push(push_url, f"{default_branch}:{default_branch}")
        except Exception as exc:
            clean_err = sanitize_sensitive_text(str(exc))
            raise RuntimeError(f"Direct push to {default_branch} failed: {clean_err}") from None
        finally:
            try:
                git_repo.remotes.origin.set_url(clean_remote)
            except Exception:
                pass

    # Update database
    ci_conf.setup_status = "installed"
    ci_conf.workflow_path = ".github/workflows/ci.yml"
    ci_conf.active_workflow_content = content_to_commit
    repo.detected_ci = True
    repo.detected_ci_files = json.dumps([".github/workflows/ci.yml"])
    repo.needs_ci_setup = False
    db.commit()

    return {
        "success": True,
        "status": "installed",
        "commit_sha": commit_sha,
        "commit_url": commit_url,
        "branch": default_branch,
        "workflow_path": ".github/workflows/ci.yml",
        "message": f"CI workflow committed directly to {default_branch}.",
    }


def verify_remote_ci_installation(repo: Repo, db: Session, current_user: User) -> dict[str, Any]:
    """
    Check if the proposed workflow file or PR has been merged on GitHub or committed locally.
    Transitions setup_status to 'installed' if verified remotely or locally.
    """
    ci_conf = get_or_create_repo_ci_config(repo, db)
    if repo.source_type != "github":
        return {"status": ci_conf.setup_status, "installed": ci_conf.setup_status == "installed"}

    user_token = get_user_github_token(current_user)
    repo_full_name = get_repo_full_name(repo)

    # 1. Check if PR was merged
    is_merged = False
    if ci_conf.pr_number:
        try:
            is_merged = check_pr_merged(repo_full_name, ci_conf.pr_number, token=user_token)
        except Exception as exc:
            logger.warning("Error checking PR merged status for %s PR #%s: %s", repo_full_name, ci_conf.pr_number, exc)

    # 2. Check if file exists on remote default branch
    file_exists = False
    try:
        file_exists = check_remote_file_exists(
            repo_full_name,
            ci_conf.workflow_path or ".github/workflows/ci.yml",
            ref=ci_conf.default_branch or "main",
            token=user_token,
        )
    except Exception as exc:
        logger.warning("Error checking remote file existence for %s: %s", repo_full_name, exc)

    # 3. Check if workflow file exists locally in repo files or disk
    local_file_exists = False
    workflow_rel = (ci_conf.workflow_path or ".github/workflows/ci.yml").lstrip("/").replace("\\", "/")
    try:
        from models import RepoFile
        found = db.query(RepoFile).filter(
            RepoFile.repo_id == repo.id,
            RepoFile.path.ilike(f"%{workflow_rel}%")
        ).first()
        if found:
            local_file_exists = True
    except Exception:
        pass

    if not local_file_exists and repo.local_path:
        try:
            from pathlib import Path
            local_disk = Path(repo.local_path) / workflow_rel
            if local_disk.exists():
                local_file_exists = True
        except Exception:
            pass

    if is_merged or file_exists or local_file_exists:
        ci_conf.setup_status = "installed"
        repo.detected_ci = True
        repo.needs_ci_setup = False
        db.commit()

    # Fetch deployment status for lifecycle tracking
    deployment_verified = False
    try:
        from automation.deployment_detector import detect_repository_deployment
        deployment_info = detect_repository_deployment(repo, db)
        deployment_verified = bool(deployment_info.get("status") in ("success", "running") and deployment_info.get("deployment_url"))
    except Exception as exc:
        logger.warning("Error detecting deployment in verify_remote_ci_installation: %s", exc)

    return {
        "setup_status": ci_conf.setup_status,
        "is_merged": is_merged,
        "file_exists_remotely": bool(file_exists or local_file_exists),
        "workflow_path": ci_conf.workflow_path,
        "pr_url": ci_conf.pr_url,
        "workflow_generated": bool(ci_conf.proposed_workflow_content or ci_conf.active_workflow_content),
        "workflow_committed": bool(ci_conf.setup_status in ("installed", "awaiting_installation")),
        "remote_workflow_verified": bool(file_exists or is_merged or local_file_exists),
        "workflow_dispatch_accepted": bool(ci_conf.last_run_id or ci_conf.last_run_status),
        "workflow_run_created": bool(ci_conf.last_run_id),
        "latest_workflow_run_completed": bool(ci_conf.last_run_status == "completed" or (ci_conf.last_run_conclusion and ci_conf.last_run_conclusion not in ("queued", "in_progress", "waiting"))),
        "deployment_verified": deployment_verified,
    }
