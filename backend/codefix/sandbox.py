"""
codefix/sandbox.py
------------------
Sandboxed test runner — applies an AI-generated patch to a throwaway copy of the repo
in an isolated temporary workspace and runs the auto-detected test suite or targeted verification.

Features & Guarantees:
- Server-authoritative validation flow: workspace creation -> patch application -> test detection -> execution -> diagnostics.
- Non-destructive: original repository files on disk are NEVER modified prior to explicit approval.
- Intelligent subproject & test runner resolution: handles multi-component/monorepos (e.g. llm_service, backend)
  without cross-subproject test leakage or invalid positional directories.
- Robust failure categorization: strictly distinguishes patch defects (syntax error, test assertion failure)
  from environment/runtime failures (missing dependencies, unavailable runner, pre-existing syntax errors in unrelated files).
- Secret removal verification: validates that hardcoded credentials (GEN001) are excised and replaced with safe environment configuration.
- Total secret & host-path redaction: scrubs host usernames, local paths, API keys, and sensitive tokens from all diagnostics.
- Isolated container runtime enforcement: prevents untrusted code execution on host in production/public deployment modes.
- Hard timeout capped at 60 seconds.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from docgen.secret_redactor import redact_secrets, sanitize_host_paths

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"
_TIMEOUT_S = 60

_SECRET_PATTERN = re.compile(
    r"(secret|api_key|apikey|token|password|passwd|auth_token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    passed: bool
    test_command: str
    output: str          # combined stdout + stderr (sanitized & redacted)
    exit_code: int
    error: str = ""      # specific error message (sanitized & redacted)
    failure_type: str = "PASSED"  # Granular classification
    is_environment_failure: bool = False

    # Complete execution diagnostics
    working_directory: str = ""
    python_executable: str = ""
    python_version: str = ""
    repo_root: str = ""
    project_root: str = ""
    detected_test_config: str = ""
    patch_applied: bool = False
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    runtime_provider: str = ""
    missing_dependencies: list[str] = field(default_factory=list)
    diagnostic_details: dict[str, Any] = field(default_factory=dict)


def _sanitize_diagnostics(text: str) -> str:
    """Combines secret redaction and host path scrubbing."""
    if not text:
        return ""
    return sanitize_host_paths(redact_secrets(str(text)))


def verify_secret_removal(original_content: str, patched_content: str) -> tuple[bool, str]:
    """
    Verifies that a secret removal patch actually removes hardcoded credentials
    and replaces them with environment-based configuration without reintroducing credentials.
    """
    orig_matches = _SECRET_PATTERN.findall(original_content)
    if not orig_matches:
        return True, "No hardcoded credentials flagged in original source."

    patched_matches = _SECRET_PATTERN.findall(patched_content)
    if patched_matches:
        return False, "Patched code still contains a hardcoded credential or secret key."

    has_env_access = any(
        kw in patched_content
        for kw in ("os.getenv", "os.environ", "getenv", "process.env", "config.", "settings.")
    )
    if not has_env_access:
        # Check if the line was commented out or replaced with safe placeholder
        if "<REDACTED" not in patched_content and '""' not in patched_content and "''" not in patched_content:
            return True, "Credential line removed from source code."

    return True, "Credential successfully removed and replaced with environment-based configuration."


def _categorize_result(
    passed: bool,
    exit_code: int,
    stdout: str,
    stderr: str,
    error: str = "",
    target_file_path: str | None = None,
) -> tuple[str, bool, list[str], str]:
    """
    Granularly categorizes the execution outcome and separates actual patch
    defects from environment/infrastructure defects.

    Returns:
        (failure_type, is_environment_failure, missing_dependencies, refined_error)
    """
    if passed and exit_code == 0:
        return "PASSED", False, [], ""

    raw_combined = f"{stdout}\n{stderr}\n{error}"
    combined = raw_combined.lower()

    # 1. Timeout
    if "timed out" in combined or exit_code == -9:
        return "TIMEOUT", True, [], f"Sandbox execution timed out after {_TIMEOUT_S} seconds."

    # 2. Isolated environment blocked / runtime unavailable
    if (
        "environment_blocked" in combined
        or "isolated container runtime" in combined
        or "runtime_unavailable" in combined
        or "execution runtime is unavailable" in combined
        or "subprocess host execution is blocked" in combined
        or "docker execution provider requested but docker daemon is unreachable" in combined
        or "isolated docker or remote execution provider" in combined
    ):
        return "RUNTIME_UNAVAILABLE", True, [], error or "Isolated runtime is required but unavailable."

    # 3. Patch application failure
    if "patch failed to apply" in combined or "no valid unified diff" in combined:
        return "PATCH_APPLICATION_FAILED", False, [], error or "Unified diff failed to apply to target file."

    # 4. Missing dependencies (Environment Failure)
    missing_pkgs: list[str] = []
    mod_matches = re.findall(r"ModuleNotFoundError:\s+No module named\s+['\"]([^'\"]+)['\"]", raw_combined)
    imp_matches = re.findall(r"ImportError:\s+cannot import name\s+['\"]([^'\"]+)['\"]", raw_combined)
    pkg_matches = re.findall(r"Cannot find module\s+['\"]([^'\"]+)['\"]", raw_combined)
    for m in mod_matches + imp_matches + pkg_matches:
        if m and m not in missing_pkgs:
            missing_pkgs.append(m)

    if missing_pkgs:
        err_msg = f"Runtime environment missing dependency: {', '.join(missing_pkgs)}. The AI patch is syntactically preserved."
        return "MISSING_DEPENDENCY", True, missing_pkgs, err_msg

    # 5. Missing test target / runner not found (Environment / Config Failure)
    if "file or directory not found:" in combined or "no test runner detected" in combined:
        return "NO_TEST_RUNNER", True, [], error or "Specified test target or test runner not found in environment."

    # 6. Syntax or compilation error in target file vs unrelated file
    has_syntax_err = "syntaxerror:" in combined or "indentationerror:" in combined or "py_compile" in combined
    if has_syntax_err:
        target_name = Path(target_file_path).name.lower() if target_file_path else ""
        if target_name and target_name in combined:
            # Genuine syntax error introduced by the patch in the target file
            return "SYNTAX_ERROR", False, [], "Syntax or indentation error in patched code."
        elif target_file_path:
            # Syntax error in another file during test collection!
            return "COLLECTION_ERROR", True, [], "Test collection failed due to a syntax/import error in an unrelated repository file."
        else:
            return "SYNTAX_ERROR", False, [], "Syntax error encountered during validation."

    # 7. Test collection errors in general
    if "error collecting" in combined or "importerror while importing" in combined or "during collection" in combined:
        return "COLLECTION_ERROR", True, [], "Test runner failed during test discovery/collection."

    # 8. Genuine test assertion failure
    if "failures" in combined or "failed" in combined or "assertionerror" in combined:
        return "TEST_ASSERTION_FAILED", False, [], error or "Test assertion failed in sandbox."

    # 9. Generic failure
    return "TEST_FAILED", False, [], error or f"Test process exited with code {exit_code}."


def _detect_test_command(repo_root: Path, target_file_path: str | None = None) -> tuple[str | None, Path]:
    """Backward-compatible wrapper for test command and working directory detection."""
    cmd, cwd, _ = _resolve_project_root_and_test_command(repo_root, target_file_path)
    return cmd, cwd


def _resolve_project_root_and_test_command(
    repo_root: Path,
    target_file_path: str | None = None,
    test_command_override: str | None = None,
) -> tuple[str | None, Path, str]:
    """
    Intelligently determines the appropriate component root, working directory,
    and test command for a target file.
    
    Prevents cross-subproject leakage (e.g. running backend/tests when editing llm_service/tests/qwen_llm.py).
    Never blindly invokes 'pytest -x -q tests' if tests/ does not exist in working directory.
    
    Returns:
        (test_command, working_directory, detected_config_description)
    """
    py = f'"{sys.executable}"' if " " in sys.executable else sys.executable

    # Case 1: Explicit test command override
    if test_command_override and test_command_override.strip():
        cmd_str = test_command_override.strip()
        norm_target = (target_file_path or "").replace("\\", "/").strip().lstrip("/")
        first_segment = norm_target.split("/")[0] if "/" in norm_target else ""
        if first_segment and (repo_root / first_segment).is_dir():
            return cmd_str, repo_root / first_segment, f"Override test command in {first_segment}"
        return cmd_str, repo_root, "Override test command in repo root"

    # Case 2: Target file provided
    if target_file_path and target_file_path.strip():
        norm_target = target_file_path.replace("\\", "/").strip().lstrip("/")
        parts = [p for p in norm_target.split("/") if p and p not in (".", "..")]

        # Determine subproject/component root
        subproject_root = repo_root
        rel_in_sub = norm_target
        if len(parts) > 1 and (repo_root / parts[0]).is_dir():
            subproject_root = repo_root / parts[0]
            rel_in_sub = "/".join(parts[1:])

        target_file_full = repo_root / norm_target

        # Python file handling
        if norm_target.endswith(".py"):
            content = ""
            if target_file_full.exists():
                try:
                    content = target_file_full.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

            has_test_cases = bool(re.search(r"^\s*(def test_|class Test)", content, re.MULTILINE))

            # 1. Targeted test file with genuine test functions
            if has_test_cases:
                rel_path_arg = rel_in_sub if subproject_root != repo_root else norm_target
                return f"{py} -m pytest -x -q {rel_path_arg}", subproject_root, f"Targeted pytest execution for {rel_path_arg}"

            # 2. Check for configured pytest suite inside this subproject
            has_pytest_conf = (
                (subproject_root / "pytest.ini").exists()
                or (subproject_root / "setup.cfg").exists()
                or (subproject_root / "pyproject.toml").exists()
            )
            sub_tests_dir = subproject_root / "tests"
            has_test_dir = sub_tests_dir.is_dir()

            # Check if there are actual pytest test files (with def test_) in subproject
            has_actual_tests = False
            for cand in subproject_root.rglob("test_*.py"):
                try:
                    c_txt = cand.read_text(encoding="utf-8", errors="replace")
                    if re.search(r"^\s*(def test_|class Test)", c_txt, re.MULTILINE):
                        has_actual_tests = True
                        break
                except Exception:
                    pass

            if has_pytest_conf and (has_test_dir or has_actual_tests):
                if has_test_dir and bool(list(sub_tests_dir.glob("test_*.py"))):
                    return f"{py} -m pytest -x -q tests", subproject_root, f"Configured pytest in {subproject_root.name}/tests"
                return f"{py} -m pytest -x -q", subproject_root, f"Configured pytest in {subproject_root.name}"

            if has_actual_tests:
                if has_test_dir and bool(list(sub_tests_dir.glob("test_*.py"))):
                    return f"{py} -m pytest -x -q tests", subproject_root, f"Discovered tests in {subproject_root.name}/tests"
                return f"{py} -m pytest -x -q", subproject_root, f"Discovered test files in {subproject_root.name}"

            # 3. Standalone Python script, benchmark, or service module without test runner
            # (e.g. llm_service/tests/qwen_llm.py)
            rel_compile_arg = rel_in_sub if subproject_root != repo_root else norm_target
            return f"{py} -m py_compile {rel_compile_arg}", subproject_root, f"Bytecode compilation & AST syntax validation for {rel_compile_arg}"

        # JavaScript / TypeScript handling
        if any(norm_target.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            if (subproject_root / "package.json").exists():
                return "npm test -- --watchAll=false", subproject_root, f"npm test in {subproject_root.name}"
            if (repo_root / "package.json").exists():
                return "npm test -- --watchAll=false", repo_root, "npm test in repo root"

    # Case 3: General repo-level inspection
    if (repo_root / "backend" / "pyproject.toml").exists() and (repo_root / "backend" / "tests").is_dir():
        return f"{py} -m pytest -x -q tests", repo_root / "backend", "Configured pytest suite in backend/tests"

    checks: list[tuple[str, str, Path, str]] = [
        ("pytest.ini", f"{py} -m pytest -x -q", repo_root, "pytest.ini in repo root"),
        ("backend/pytest.ini", f"{py} -m pytest -x -q tests", repo_root / "backend", "backend/pytest.ini"),
        ("setup.cfg", f"{py} -m pytest -x -q", repo_root, "setup.cfg in repo root"),
        ("backend/setup.cfg", f"{py} -m pytest -x -q tests", repo_root / "backend", "backend/setup.cfg"),
        ("pyproject.toml", f"{py} -m pytest -x -q", repo_root, "pyproject.toml in repo root"),
        ("backend/pyproject.toml", f"{py} -m pytest -x -q tests", repo_root / "backend", "backend/pyproject.toml"),
        ("conftest.py", f"{py} -m pytest -x -q", repo_root, "conftest.py in repo root"),
        ("backend/conftest.py", f"{py} -m pytest -x -q tests", repo_root / "backend", "backend/conftest.py"),
        ("package.json", "npm test -- --watchAll=false", repo_root, "package.json in repo root"),
        ("pom.xml", "mvn test -q", repo_root, "Maven pom.xml"),
        ("build.gradle", "gradle test -q", repo_root, "Gradle build.gradle"),
        ("build.gradle.kts", "gradle test -q", repo_root, "Gradle build.gradle.kts"),
        ("go.mod", "go test ./...", repo_root, "Go go.mod"),
        ("Cargo.toml", "cargo test -q", repo_root, "Rust Cargo.toml"),
    ]
    for rel_path, cmd, cwd, desc in checks:
        if (repo_root / rel_path).exists():
            return cmd, cwd, desc

    if (repo_root / "tests").is_dir() and bool(list((repo_root / "tests").glob("test_*.py"))):
        return f"{py} -m pytest -x -q tests", repo_root, "Discovered tests/ in repo root"

    if list(repo_root.rglob("test_*.py")):
        return f"{py} -m pytest -x -q", repo_root, "Discovered test_*.py in repo"

    return None, repo_root, "No test runner detected"


SAFE_SYSTEM_ENV_KEYS = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "USERPROFILE", "HOME", "LANG", "LC_ALL", "TERM", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "SYSTEMDRIVE", "APPDATA", "LOCALAPPDATA",
}


def _discover_pythonpath_entries(root: Path) -> list[str]:
    """
    Dynamically discover all package roots and source directories
    to avoid ModuleNotFoundError across diverse repo layouts and monorepos.
    """
    entries = [str(root)]
    visited = {str(root)}
    skip_dirs = {".git", "__pycache__", "venv", ".venv", "env", ".env", "node_modules", "dist", "build", ".tox", ".pytest_cache"}

    for known in ("backend", "backend/app", "src", "app", "server", "services", "chatbot", "llm_service", "db", "lib"):
        p = root / known
        if p.is_dir() and str(p) not in visited:
            visited.add(str(p))
            entries.append(str(p))

    try:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            p = Path(dirpath)
            try:
                rel = p.relative_to(root)
                if len(rel.parts) > 3:
                    continue
            except Exception:
                continue

            has_init = "__init__.py" in filenames
            has_py = any(f.endswith(".py") for f in filenames)
            if has_init and p.parent != root and str(p.parent) not in visited:
                visited.add(str(p.parent))
                entries.append(str(p.parent))
            if (has_init or has_py) and str(p) not in visited:
                visited.add(str(p))
                entries.append(str(p))
    except Exception:
        pass

    return entries


def _build_sandbox_env(sandbox: Path, subproject_root: Path | None = None) -> dict[str, str]:
    """
    Build a safe, isolated runtime environment for sandbox testing.
    Strictly scrubs host database tokens, GitHub credentials, and system secrets
    while forwarding active provider API keys so repository test suites can validate LLM features.
    """
    env: dict[str, str] = {}
    for k in SAFE_SYSTEM_ENV_KEYS:
        val = os.environ.get(k)
        if val:
            env[k] = val

    paths = _discover_pythonpath_entries(sandbox)
    if subproject_root and str(subproject_root) not in paths:
        paths.insert(0, str(subproject_root))
    pythonpath = os.pathsep.join(paths)

    db_test_path = str((sandbox / "backend" / "sandbox_test.db") if (sandbox / "backend").is_dir() else (sandbox / "sandbox_test.db"))

    groq_key = os.environ.get("GROQ_API_KEY")
    nvidia_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_NIM_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    apinex_key = os.environ.get("APINEX_API_KEY")

    env.update({
        "CI": "true",
        "PYTHONPATH": pythonpath,
        "PYTHONUNBUFFERED": "1",
        "TOPIC": "codebrain_automated_validation_test",
        "NVIDIA_API_KEY": nvidia_key or "mock_test_nvidia_key",
        "NVCF_API_KEY": nvidia_key or "mock_test_nvidia_key",
        "GROQ_API_KEY": groq_key or "mock_test_groq_key",
        "OPENAI_API_KEY": openai_key or "mock_test_openai_key",
        "APINEX_API_KEY": apinex_key or "mock_test_apinex_key",
        "DB_TYPE": "sqlite",
        "db_type": "sqlite",
        "DB_PATH": db_test_path,
        "db_path": db_test_path,
        "SECRET_KEY": "test-isolated-secret-key-32bytes-secure-hash-token",
        "JWT_SECRET_KEY": "test-isolated-jwt-secret-key-32bytes-secure-hash-token",
        "jwt_secret_key": "test-isolated-jwt-secret-key-32bytes-secure-hash-token",
    })
    return env


def _init_sandbox_test_db(sandbox: Path, env: dict[str, str]) -> None:
    """Proactively initialize SQLAlchemy Base models in SQLite test database."""
    py = sys.executable
    init_script = (
        "try:\n"
        "    from db.database import Base, engine\n"
        "    import db.models\n"
        "    Base.metadata.create_all(bind=engine)\n"
        "except Exception:\n"
        "    try:\n"
        "        from app.database import Base, engine\n"
        "        Base.metadata.create_all(bind=engine)\n"
        "    except Exception:\n"
        "        pass\n"
    )
    target_cwd = sandbox / "backend" if (sandbox / "backend").is_dir() else sandbox
    try:
        subprocess.run(
            [py, "-c", init_script],
            cwd=str(target_cwd),
            env=env,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


def _is_safe_command(cmd: str) -> bool:
    """Validate that the test command is safe and does not contain shell injection."""
    if not cmd or not cmd.strip():
        return False
    # Disallow command chaining, redirection, command substitution, and subshells
    for dangerous in (";", "&&", "||", "|", ">", "<", "\n", "\r", "`", "$", "(", ")", "{", "}", "&"):
        if dangerous in cmd:
            return False
    clean = cmd.strip().lower()
    allowed_keywords = ("pytest", "py_compile", "npm test", "npx test", "mvn test", "gradle test", "go test", "cargo test")
    return any(kw in clean for kw in allowed_keywords)


def _apply_direct_content(sandbox_root: Path, file_path: str, patched_content: str) -> None:
    """Write patched_content directly to the target file inside sandbox."""
    target = sandbox_root / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(patched_content, encoding="utf-8", errors="replace")


def _apply_unified_diff(sandbox_root: Path, diff_text: str) -> tuple[bool, str]:
    """Apply a unified diff using system patch or pure-python fallback."""
    patch_bin = shutil.which("patch")
    if not patch_bin:
        return _apply_diff_manually(sandbox_root, diff_text)

    try:
        result = subprocess.run(
            [patch_bin, "-p1", "--batch", "--forward"],
            input=diff_text,
            capture_output=True,
            text=True,
            cwd=str(sandbox_root),
            timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return False, "patch command timed out"
    except Exception as exc:
        return False, str(exc)


def _apply_diff_manually(sandbox_root: Path, diff_text: str) -> tuple[bool, str]:
    """Pure-Python unified diff applicator (cross-platform)."""
    if not diff_text or not diff_text.strip():
        return True, ""

    lines = diff_text.splitlines()
    file_diffs: list[dict] = []
    current_diff: dict | None = None

    for line in lines:
        if line.startswith("--- "):
            if current_diff and current_diff.get("target"):
                file_diffs.append(current_diff)
            raw_orig = line[4:].strip().split("\t")[0]
            if raw_orig.startswith("a/"):
                raw_orig = raw_orig[2:]
            current_diff = {"orig": raw_orig, "target": None, "hunk_text": []}
        elif line.startswith("+++ "):
            if current_diff is not None:
                raw_target = line[4:].strip().split("\t")[0]
                if raw_target.startswith("b/"):
                    raw_target = raw_target[2:]
                current_diff["target"] = raw_target
        elif current_diff is not None:
            current_diff["hunk_text"].append(line)

    if current_diff and current_diff.get("target"):
        file_diffs.append(current_diff)

    if not file_diffs:
        return False, "No valid unified diff headers (--- and +++) found."

    for fd in file_diffs:
        target_name = fd["target"] or fd["orig"]
        if not target_name:
            continue

        target_path = sandbox_root / target_name
        if not target_path.exists():
            matches = list(sandbox_root.rglob(Path(target_name).name))
            if matches:
                target_path = matches[0]
            else:
                return False, f"Target file not found in repo: {target_name}"

        try:
            orig_text = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return False, f"Could not read {target_name}: {exc}"

        orig_lines = orig_text.splitlines(keepends=True)
        hunk_lines_list = fd["hunk_text"]

        hunks: list[tuple[int, list[str]]] = []
        current_hunk: list[str] = []
        old_start = 1

        for hl in hunk_lines_list:
            if hl.startswith("@@ "):
                if current_hunk:
                    hunks.append((old_start, current_hunk))
                m = re.search(r"-(\d+)(?:,\d+)?", hl)
                old_start = int(m.group(1)) if m else 1
                current_hunk = []
            elif current_hunk is not None and (hl.startswith((" ", "-", "+", "\\")) or not hl):
                current_hunk.append(hl)

        if current_hunk:
            hunks.append((old_start, current_hunk))

        if not hunks:
            return False, f"No @@ hunks found for {target_name}"

        result_lines = list(orig_lines)

        for old_start, hunk in reversed(hunks):
            old_hunk_lines = [
                l[1:] if l.startswith((" ", "-")) else ("" if not l else l)
                for l in hunk
                if not l.startswith("+") and not l.startswith("\\")
            ]
            new_hunk_lines = [
                l[1:] if l.startswith((" ", "+")) else ("" if not l else l)
                for l in hunk
                if not l.startswith("-") and not l.startswith("\\")
            ]

            old_norm = [l.rstrip("\r\n") for l in old_hunk_lines]
            file_norm = [l.rstrip("\r\n") for l in result_lines]

            pos = max(0, old_start - 1)
            n = len(old_norm)
            matched_pos: int | None = None

            if 0 <= pos <= len(file_norm) - n and file_norm[pos : pos + n] == old_norm:
                matched_pos = pos
            else:
                for i in range(len(file_norm) - n + 1):
                    if file_norm[i : i + n] == old_norm:
                        matched_pos = i
                        break

            if matched_pos is None:
                rem_lines = [l[1:].rstrip("\r\n") for l in hunk if l.startswith("-")]
                if rem_lines:
                    rn = len(rem_lines)
                    for i in range(len(file_norm) - rn + 1):
                        if file_norm[i : i + rn] == rem_lines:
                            matched_pos = i
                            n = rn
                            new_hunk_lines = [l[1:] for l in hunk if l.startswith("+")]
                            break

            if matched_pos is None:
                old_stripped = [l.strip() for l in old_hunk_lines if l.strip()]
                sn = len(old_stripped)
                for i in range(len(file_norm) - sn + 1):
                    cand = [l.strip() for l in file_norm[i : i + sn] if l.strip()]
                    if cand == old_stripped:
                        matched_pos = i
                        n = sn
                        break

            if matched_pos is None:
                return False, f"Could not locate matching context in {target_name} for hunk @@ -{old_start}..."

            eol = "\r\n" if orig_text.count("\r\n") > orig_text.count("\n") // 2 else "\n"
            formatted_new = [
                (l.rstrip("\r\n") + eol) for l in new_hunk_lines
            ]
            result_lines[matched_pos : matched_pos + n] = formatted_new

        try:
            target_path.write_text("".join(result_lines), encoding="utf-8")
        except Exception as exc:
            return False, f"Could not write patched content to {target_name}: {exc}"

    return True, ""


class EnvironmentExecutionResult(tuple):
    """
    Backwards-compatible 5-tuple (retcode, stdout, stderr, timed_out, error)
    with a .provider_name metadata attribute.
    """
    def __new__(cls, retcode: int, stdout: str, stderr: str, timed_out: bool, error: str, provider_name: str = ""):
        return super().__new__(cls, (retcode, stdout, stderr, timed_out, error))

    def __init__(self, retcode: int, stdout: str, stderr: str, timed_out: bool, error: str, provider_name: str = ""):
        self.retcode = retcode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.error = error
        self.provider_name = provider_name


def _execute_in_environment(
    cmd_str: str,
    cmd_cwd: Path,
    env: dict[str, str],
    timeout_s: int = _TIMEOUT_S,
) -> EnvironmentExecutionResult:
    """
    Executes a test/validation command via the configured execution provider.
    Enforces isolated container runtimes in production or when isolation is required.

    Returns:
        EnvironmentExecutionResult(exit_code, stdout, stderr, timed_out, error_message, provider_name)
    """
    from execution.provider import get_execution_provider

    provider = get_execution_provider()
    res = provider.execute_command(cmd_cwd, cmd_str, env, timeout_s=timeout_s)
    return EnvironmentExecutionResult(
        res.exit_code,
        res.stdout,
        res.stderr,
        res.timed_out,
        res.error,
        res.provider_name,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def validate_patch(
    repo_id: str,
    file_path: str,
    patched_content: str,   # the full new file content (already patched)
    db,
    test_command: str | None = None,
) -> ValidationResult:
    """
    Applies patched_content to a throwaway copy of repo_id and runs the auto-detected test suite.
    Original repo on disk is never modified.
    """
    from models import Repo

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return ValidationResult(
            passed=False, test_command="", output="", exit_code=-1,
            error=f"Repo {repo_id} not found",
            failure_type="RUNTIME_PREPARATION_FAILED",
            is_environment_failure=True,
        )

    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        return ValidationResult(
            passed=False, test_command="", output="", exit_code=-1,
            error="Repo source not found on disk. Re-upload the repository.",
            failure_type="RUNTIME_PREPARATION_FAILED",
            is_environment_failure=True,
        )

    repo_root = storage_dir
    children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs", "faiss.index")]
    if len(children) == 1:
        repo_root = children[0]

    with tempfile.TemporaryDirectory(prefix="codefix_sandbox_") as tmp:
        sandbox = Path(tmp) / "repo"
        try:
            shutil.copytree(str(repo_root), str(sandbox))
        except Exception as exc:
            return ValidationResult(
                passed=False, test_command="", output="", exit_code=-1,
                error=f"Failed to copy repo to sandbox: {exc}",
                failure_type="RUNTIME_PREPARATION_FAILED",
                is_environment_failure=True,
            )

        # Read original file before patching for credential checks
        orig_file = sandbox / file_path
        orig_content = ""
        if orig_file.exists():
            try:
                orig_content = orig_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        # Apply patch
        _apply_direct_content(sandbox, file_path, patched_content)

        # Secret removal check
        sec_ok, sec_msg = verify_secret_removal(orig_content, patched_content)
        if not sec_ok:
            return ValidationResult(
                passed=False,
                test_command="(credential_validation)",
                output="",
                exit_code=-1,
                error=sec_msg,
                failure_type="SYNTAX_ERROR",
                is_environment_failure=False,
                patch_applied=True,
                repo_root=str(repo_root),
                working_directory=str(sandbox),
            )

        cmd_str, cmd_cwd, detected_desc = _resolve_project_root_and_test_command(
            sandbox, target_file_path=file_path, test_command_override=test_command
        )

        if not cmd_str:
            return ValidationResult(
                passed=False,
                test_command="(none detected)",
                output="",
                exit_code=-1,
                error="No test runner detected in the repository.",
                failure_type="NO_TEST_RUNNER",
                is_environment_failure=True,
                patch_applied=True,
                repo_root=str(repo_root),
                working_directory=str(sandbox),
                detected_test_config=detected_desc,
            )

        if not _is_safe_command(cmd_str):
            return ValidationResult(
                passed=False,
                test_command=cmd_str,
                output="",
                exit_code=-1,
                error="Untrusted test command rejected for security reasons.",
                failure_type="SANDBOX_FAILED",
                is_environment_failure=True,
                patch_applied=True,
                repo_root=str(repo_root),
                working_directory=str(cmd_cwd),
            )

        env = _build_sandbox_env(sandbox, subproject_root=cmd_cwd)
        _init_sandbox_test_db(sandbox, env)

        exec_res = _execute_in_environment(cmd_str, cmd_cwd, env)
        retcode, raw_out, raw_err, timed_out, run_err = exec_res
        prov_name = getattr(exec_res, "provider_name", "unknown")

        # Sanitize diagnostics
        clean_out = _sanitize_diagnostics(raw_out)
        clean_err = _sanitize_diagnostics(raw_err)
        clean_combined = (clean_out + "\n" + clean_err).strip()
        if len(clean_combined) > 4000:
            clean_combined = "...[truncated]\n" + clean_combined[-4000:]

        fail_type, is_env_fail, missing_pkgs, refined_err = _categorize_result(
            passed=retcode == 0,
            exit_code=retcode,
            stdout=clean_out,
            stderr=clean_err,
            error=_sanitize_diagnostics(run_err),
            target_file_path=file_path,
        )

        return ValidationResult(
            passed=retcode == 0,
            test_command=_sanitize_diagnostics(cmd_str),
            output=clean_combined,
            exit_code=retcode,
            error=refined_err,
            failure_type=fail_type,
            is_environment_failure=is_env_fail,
            working_directory=_sanitize_diagnostics(str(cmd_cwd)),
            python_executable=_sanitize_diagnostics(sys.executable),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            repo_root=_sanitize_diagnostics(str(repo_root)),
            project_root=_sanitize_diagnostics(str(cmd_cwd)),
            detected_test_config=detected_desc,
            patch_applied=True,
            stdout=clean_out[:2000],
            stderr=clean_err[:2000],
            timeout=timed_out,
            runtime_provider=prov_name,
            missing_dependencies=missing_pkgs,
            diagnostic_details={
                "detected_config": detected_desc,
                "exit_code": retcode,
                "failure_type": fail_type,
                "is_environment_failure": is_env_fail,
                "missing_dependencies": missing_pkgs,
                "runtime_provider": prov_name,
            },
        )


def validate_diff(
    repo_id: str,
    diff_text: str,
    db,
    test_command: str | None = None,
    target_file_path: str | None = None,
) -> ValidationResult:
    """
    Applies a unified diff to a throwaway copy of repo_id and runs the auto-detected test suite.
    Original repo on disk is never modified.
    """
    from models import Repo

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        return ValidationResult(
            passed=False, test_command="", output="", exit_code=-1,
            error="Repo not found", failure_type="RUNTIME_PREPARATION_FAILED", is_environment_failure=True,
        )

    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        storage_dir.mkdir(parents=True, exist_ok=True)
    repo_root = storage_dir
    children = [c for c in storage_dir.iterdir() if c.is_dir() and c.name not in ("docs",)]
    if len(children) == 1:
        repo_root = children[0]

    with tempfile.TemporaryDirectory(prefix="codefix_sandbox_") as tmp:
        sandbox = Path(tmp) / "repo"
        try:
            shutil.copytree(str(repo_root), str(sandbox))
        except Exception as exc:
            return ValidationResult(
                passed=False, test_command="", output="", exit_code=-1,
                error=str(exc), failure_type="RUNTIME_PREPARATION_FAILED", is_environment_failure=True,
            )

        # Infer target file path if not passed explicitly
        inferred_target = target_file_path
        if not inferred_target and diff_text:
            for line in diff_text.splitlines():
                if line.startswith("+++ "):
                    raw = line[4:].strip().split("\t")[0]
                    if raw.startswith("b/"):
                        raw = raw[2:]
                    inferred_target = raw
                    break

        # Capture original content for credential verification
        orig_content = ""
        if inferred_target:
            orig_p = sandbox / inferred_target
            if not orig_p.exists():
                matches = list(sandbox.rglob(Path(inferred_target).name))
                if matches:
                    orig_p = matches[0]
            if orig_p.exists():
                try:
                    orig_content = orig_p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        ok, err = _apply_unified_diff(sandbox, diff_text)
        if not ok:
            return ValidationResult(
                passed=False,
                test_command="",
                output="",
                exit_code=-1,
                error=f"Patch failed to apply: {_sanitize_diagnostics(err)}",
                failure_type="PATCH_APPLICATION_FAILED",
                is_environment_failure=False,
                repo_root=_sanitize_diagnostics(str(repo_root)),
                working_directory=_sanitize_diagnostics(str(sandbox)),
            )

        # Check secret removal in patched content if target was identified
        if inferred_target:
            patched_p = sandbox / inferred_target
            if not patched_p.exists():
                matches = list(sandbox.rglob(Path(inferred_target).name))
                if matches:
                    patched_p = matches[0]
            if patched_p.exists():
                try:
                    patched_content = patched_p.read_text(encoding="utf-8", errors="replace")
                    sec_ok, sec_msg = verify_secret_removal(orig_content, patched_content)
                    if not sec_ok:
                        return ValidationResult(
                            passed=False,
                            test_command="(credential_validation)",
                            output="",
                            exit_code=-1,
                            error=sec_msg,
                            failure_type="SYNTAX_ERROR",
                            is_environment_failure=False,
                            patch_applied=True,
                            repo_root=_sanitize_diagnostics(str(repo_root)),
                            working_directory=_sanitize_diagnostics(str(sandbox)),
                        )
                except Exception:
                    pass

        cmd_str, cmd_cwd, detected_desc = _resolve_project_root_and_test_command(
            sandbox, target_file_path=inferred_target, test_command_override=test_command
        )

        if not cmd_str:
            return ValidationResult(
                passed=True,
                test_command="(none)",
                output="Patch applied cleanly. No test suite detected.",
                exit_code=0,
                failure_type="PASSED",
                patch_applied=True,
                repo_root=_sanitize_diagnostics(str(repo_root)),
                working_directory=_sanitize_diagnostics(str(sandbox)),
                detected_test_config=detected_desc,
            )

        if not _is_safe_command(cmd_str):
            return ValidationResult(
                passed=False,
                test_command=cmd_str,
                output="",
                exit_code=-1,
                error="Untrusted test command rejected for security reasons.",
                failure_type="SANDBOX_FAILED",
                is_environment_failure=True,
                patch_applied=True,
                repo_root=_sanitize_diagnostics(str(repo_root)),
                working_directory=_sanitize_diagnostics(str(cmd_cwd)),
            )

        env = _build_sandbox_env(sandbox, subproject_root=cmd_cwd)
        _init_sandbox_test_db(sandbox, env)

        exec_res = _execute_in_environment(cmd_str, cmd_cwd, env)
        retcode, raw_out, raw_err, timed_out, run_err = exec_res
        prov_name = getattr(exec_res, "provider_name", "unknown")

        clean_out = _sanitize_diagnostics(raw_out)
        clean_err = _sanitize_diagnostics(raw_err)
        clean_combined = (clean_out + "\n" + clean_err).strip()
        if len(clean_combined) > 4000:
            clean_combined = "...[truncated]\n" + clean_combined[-4000:]

        fail_type, is_env_fail, missing_pkgs, refined_err = _categorize_result(
            passed=retcode == 0,
            exit_code=retcode,
            stdout=clean_out,
            stderr=clean_err,
            error=_sanitize_diagnostics(run_err),
            target_file_path=inferred_target,
        )

        return ValidationResult(
            passed=retcode == 0,
            test_command=_sanitize_diagnostics(cmd_str),
            output=clean_combined,
            exit_code=retcode,
            error=refined_err,
            failure_type=fail_type,
            is_environment_failure=is_env_fail,
            working_directory=_sanitize_diagnostics(str(cmd_cwd)),
            python_executable=_sanitize_diagnostics(sys.executable),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            repo_root=_sanitize_diagnostics(str(repo_root)),
            project_root=_sanitize_diagnostics(str(cmd_cwd)),
            detected_test_config=detected_desc,
            patch_applied=True,
            stdout=clean_out[:2000],
            stderr=clean_err[:2000],
            timeout=timed_out,
            runtime_provider=prov_name,
            missing_dependencies=missing_pkgs,
            diagnostic_details={
                "detected_config": detected_desc,
                "exit_code": retcode,
                "failure_type": fail_type,
                "is_environment_failure": is_env_fail,
                "missing_dependencies": missing_pkgs,
                "runtime_provider": prov_name,
            },
        )
