"""
gitops/git_ops.py
-----------------
Branch-and-commit helper using GitPython.

Public API
----------
create_branch_and_commit(repo_id, patch, branch_name, commit_message)
    -> BranchResult(branch_name, commit_sha, remote_url, provider)

The function:
  1. Opens the GitPython Repo at storage/<repo_id>.
  2. Creates (or resets) <branch_name> from the default branch HEAD.
  3. Applies the unified diff patch (or full-file content) to the working tree.
  4. Stages + commits all changes.
  5. Pushes the branch to origin using the configured credentials.
  6. Returns structured metadata including the detected remote provider.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

Provider = Literal["github", "unknown"]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BranchResult:
    branch_name: str
    commit_sha: str
    remote_url: str        # sanitised (no embedded token)
    provider: Provider
    default_branch: str = "main"


# ── Provider detection ────────────────────────────────────────────────────────

def _detect_provider(remote_url: str) -> Provider:
    """Infer hosting platform from the remote URL."""
    url = remote_url.lower()
    if "github.com" in url:
        return "github"
    return "unknown"


def sanitize_sensitive_text(text: str) -> str:
    """
    Redact GitHub tokens, passwords, and embedded URL credentials from any text,
    exception message, command line, or subprocess output.
    """
    if not text:
        return text
    # 1. Redact URL embedded credentials (https://user:token@... or https://token@...)
    text = re.sub(r"https?://[^@\s]+@", "https://[REDACTED_AUTH]@", text)
    # 2. Redact GitHub personal access tokens, OAuth tokens, fine-grained tokens
    text = re.sub(r"gh[opusr]_[A-Za-z0-9_]{10,}", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]{10,}", "[REDACTED_GITHUB_TOKEN]", text)
    # 3. Redact Authorization headers if captured in logs
    text = re.sub(r"(?i)(authorization:\s*(?:bearer|token|basic)\s+)[A-Za-z0-9_\-\.~]+", r"\1[REDACTED]", text)
    return text


def _sanitise_url(url: str) -> str:
    """Strip embedded credentials from a URL for logging/returning."""
    return sanitize_sensitive_text(url)


def _inject_credentials(remote_url: str, provider: Provider, token: str | None = None) -> str:
    """
    Return a push-ready URL with credentials embedded.
    Prefers user-specific token when provided; falls back to env vars.
    Strips any existing credentials first to prevent double-injection and invalid hostnames.
    """
    if "://" not in remote_url:
        # SSH URL — return as-is; credential injection only works for HTTPS
        return remote_url

    # Strip existing credentials first to avoid double '@' signs causing 'Bad hostname'
    clean_url = re.sub(r"https?://[^@]+@", "https://", remote_url)

    if provider == "github":
        gh_token = token or os.environ.get("GITHUB_TOKEN", "")
        if gh_token and clean_url.startswith("https://"):
            return clean_url.replace("https://", f"https://x-access-token:{gh_token}@", 1)

    return clean_url


# ── Diff application ──────────────────────────────────────────────────────────

def _apply_unified_diff(repo_root: Path, diff_text: str) -> None:
    """
    Apply a unified diff to the working tree.
    Tries the system `patch` binary first; falls back to a pure-Python applicator.
    Raises RuntimeError on failure.
    """
    patch_bin = shutil.which("patch")
    if patch_bin:
        import subprocess
        result = subprocess.run(
            [patch_bin, "-p1", "--batch", "--forward"],
            input=diff_text,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=15,
        )
        if result.returncode == 0:
            return
        raise RuntimeError(f"patch failed: {result.stderr or result.stdout}")

    # Pure-Python fallback (Windows / no patch binary)
    _apply_diff_python(repo_root, diff_text)


def _apply_diff_python(repo_root: Path, diff_text: str) -> None:
    """
    Robust Python unified-diff applicator that supports:
    - New file creation (--- /dev/null +++ b/path)
    - File modification
    - File deletion (+++ /dev/null)
    - Multi-file diffs
    - Automatic parent directory creation
    - Safe workspace containment validation
    """
    import re as _re

    # Split diff into per-file chunks
    lines = diff_text.splitlines()
    file_chunks: list[dict[str, Any]] = []
    current_chunk: dict[str, Any] | None = None

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old_path_raw = line[4:].strip().split("\t")[0]
            if old_path_raw.startswith("a/"):
                old_path_raw = old_path_raw[2:]

            # Look ahead for +++
            new_path_raw = ""
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                new_path_raw = lines[i + 1][4:].strip().split("\t")[0]
                if new_path_raw.startswith("b/"):
                    new_path_raw = new_path_raw[2:]
                i += 1

            if current_chunk:
                file_chunks.append(current_chunk)

            current_chunk = {
                "old_path": old_path_raw,
                "new_path": new_path_raw,
                "hunks": [],
            }
        elif line.startswith("@@ ") and current_chunk is not None:
            m = _re.search(r"-(\d+)(?:,\d+)? \+(\d+)(?:,\d+)?", line)
            orig_start = int(m.group(1)) if m else 1
            new_start = int(m.group(2)) if m else 1
            hunk_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(("--- ", "@@ ")):
                if lines[i].startswith("diff --git"):
                    break
                hunk_lines.append(lines[i])
                i += 1
            current_chunk["hunks"].append((orig_start, new_start, hunk_lines))
            continue
        i += 1

    if current_chunk:
        file_chunks.append(current_chunk)

    if not file_chunks:
        raise RuntimeError("Could not determine target file from diff: missing unified diff headers")

    for chunk in file_chunks:
        old_path = chunk["old_path"]
        new_path = chunk["new_path"]
        hunks = chunk["hunks"]

        is_new_file = old_path in ("/dev/null", "dev/null", "")
        is_deleted_file = new_path in ("/dev/null", "dev/null", "")

        target_rel = new_path if not is_deleted_file else old_path
        if not target_rel:
            continue

        target_path = (repo_root / target_rel).resolve()
        resolved_root = repo_root.resolve()

        # Path traversal guard
        try:
            target_path.relative_to(resolved_root)
        except ValueError:
            raise RuntimeError(f"Security error: Target path '{target_rel}' escapes repository root.")

        if is_deleted_file:
            if target_path.exists():
                target_path.unlink()
            continue

        # Ensure parent directories exist
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if is_new_file or not target_path.exists():
            # Brand new file: collect lines added with +
            new_content_lines: list[str] = []
            for _, _, hunk_lines in hunks:
                for hl in hunk_lines:
                    if hl.startswith("+"):
                        new_content_lines.append(hl[1:])
                    elif not hl.startswith("-"):
                        # context line
                        new_content_lines.append(hl[1:] if hl.startswith(" ") else hl)
            content = "\n".join(new_content_lines)
            if new_content_lines and not content.endswith("\n"):
                content += "\n"
            target_path.write_text(content, encoding="utf-8")
        else:
            # File modification
            orig_lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            result_lines: list[str] = []
            orig_idx = 0

            for orig_start, _, hunk_lines in hunks:
                target_start = max(0, orig_start - 1)
                # Copy all unchanged lines before this hunk
                while orig_idx < target_start and orig_idx < len(orig_lines):
                    result_lines.append(orig_lines[orig_idx])
                    orig_idx += 1

                for hl in hunk_lines:
                    if hl.startswith("+"):
                        line_content = hl[1:]
                        if not line_content.endswith("\n"):
                            line_content += "\n"
                        result_lines.append(line_content)
                    elif hl.startswith("-"):
                        # Delete this line from original
                        orig_idx += 1
                    elif hl.startswith(" ") or hl == "":
                        # Context line: keep from original
                        if orig_idx < len(orig_lines):
                            result_lines.append(orig_lines[orig_idx])
                            orig_idx += 1
                        else:
                            ctx = hl[1:] if hl.startswith(" ") else hl
                            if not ctx.endswith("\n"):
                                ctx += "\n"
                            result_lines.append(ctx)

            # Copy any remaining lines after the last hunk
            while orig_idx < len(orig_lines):
                result_lines.append(orig_lines[orig_idx])
                orig_idx += 1

            target_path.write_text("".join(result_lines), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def create_branch_and_commit(
    repo_id: str,
    patch: str,
    branch_name: str,
    commit_message: str,
    *,
    author_name: str = "CodeBrain Bot",
    author_email: str = "codebrain@noreply.local",
    token: str | None = None,
) -> BranchResult:
    """
    Create a new Git branch, apply the diff patch, commit, and push to origin.

    Args:
        repo_id:        Internal repo UUID (maps to storage/<repo_id>).
        patch:          Unified diff string (git format) produced by Phase 6 fixer.
        branch_name:    Name for the new branch (e.g. "codebrain/fix-auth-module").
        commit_message: Git commit message.
        author_name:    Commit author display name.
        author_email:   Commit author email.
        token:          Optional user-specific GitHub token for authentication.

    Returns:
        BranchResult with branch_name, commit_sha, sanitised remote_url, provider.

    Raises:
        RuntimeError:   If the repo storage is missing, git is unavailable,
                        or the push fails.
    """
    try:
        from git import Repo as GitRepo, GitCommandError, Actor
    except ImportError:
        raise RuntimeError("gitpython is not installed — run: pip install gitpython")

    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        raise RuntimeError(f"Repo storage not found at {storage_dir}. Re-upload the repository.")

    # Resolve repo root (may be a nested subdir for zip-uploaded repos)
    repo_root = storage_dir
    children = [
        c for c in storage_dir.iterdir()
        if c.is_dir() and c.name not in ("__pycache__", ".venv", "faiss.index")
    ]
    if len(children) == 1 and (children[0] / ".git").exists():
        repo_root = children[0]
    elif not (repo_root / ".git").exists():
        raise RuntimeError(
            "No .git directory found in the stored repo. "
            "Only repositories cloned from GitHub support branch/PR creation. "
            "Zip-uploaded repos without a .git directory are not supported."
        )

    git_repo = GitRepo(str(repo_root))

    # Detect provider from origin URL
    try:
        remote_url = git_repo.remotes["origin"].url
    except (IndexError, KeyError, AttributeError):
        remote_url = ""

    provider = _detect_provider(remote_url)
    push_url = _inject_credentials(remote_url, provider, token=token)
    sanitised_url = _sanitise_url(remote_url)

    # Resolve default branch (main / master)
    default_branch = "main"
    try:
        head_ref = git_repo.git.symbolic_ref("refs/remotes/origin/HEAD")
        default_branch = head_ref.split("/")[-1]
    except Exception:
        try:
            default_branch = git_repo.active_branch.name
        except Exception:
            pass

    # Create / reset branch safely and idempotently
    try:
        # If currently on the target branch, switch to default branch first to allow reset/clean checkout
        if git_repo.head.is_valid() and not git_repo.head.is_detached:
            if git_repo.active_branch.name == branch_name:
                try:
                    git_repo.git.checkout(default_branch)
                except Exception:
                    pass

        if branch_name in [b.name for b in git_repo.branches]:
            try:
                git_repo.git.branch("-D", branch_name)
            except Exception:
                pass

        # Try branching from origin/default_branch or local default_branch
        try:
            git_repo.git.checkout("-B", branch_name, f"origin/{default_branch}")
        except Exception:
            try:
                git_repo.git.checkout("-B", branch_name, default_branch)
            except Exception:
                git_repo.git.checkout("-B", branch_name)
    except Exception as exc:
        raise RuntimeError(f"Could not create branch '{branch_name}': {exc}")

    # Apply the diff
    try:
        _apply_unified_diff(repo_root, patch)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to apply patch: {exc}")

    # Stage all changes
    git_repo.git.add("-A")

    # Commit
    author = Actor(author_name, author_email)
    commit = git_repo.index.commit(
        commit_message,
        author=author,
        committer=author,
    )
    commit_sha = commit.hexsha

    try:
        git_repo.git.push(push_url, f"{branch_name}:{branch_name}", "--force-with-lease")
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        raise RuntimeError(
            f"Push failed for branch '{branch_name}' to {sanitised_url}: {clean_err}"
        ) from None

    logger.info(
        "Pushed branch '%s' (commit %s) to %s [%s]",
        branch_name,
        commit_sha[:8],
        sanitised_url,
        provider,
    )

    return BranchResult(
        branch_name=branch_name,
        commit_sha=commit_sha,
        remote_url=sanitised_url,
        provider=provider,
        default_branch=default_branch,
    )


def commit_and_push_documentation(
    repo_id: str,
    docs_dir: Path,
    branch_name: str,
    commit_message: str,
    *,
    author_name: str = "CodeBrain Bot",
    author_email: str = "codebrain@noreply.local",
    token: str | None = None,
) -> BranchResult:
    """
    Create a new Git branch, copy the generated README and docs folder into the repo, commit, and push to origin.
    """
    try:
        from git import Repo as GitRepo, GitCommandError, Actor
    except ImportError:
        raise RuntimeError("gitpython is not installed — run: pip install gitpython")

    storage_dir = STORAGE_ROOT / repo_id
    if not storage_dir.exists():
        raise RuntimeError(f"Repo storage not found at {storage_dir}. Re-upload the repository.")

    repo_root = storage_dir
    children = [
        c for c in storage_dir.iterdir()
        if c.is_dir() and c.name not in ("__pycache__", ".venv", "faiss.index", "docs")
    ]
    if len(children) == 1 and (children[0] / ".git").exists():
        repo_root = children[0]
    elif not (repo_root / ".git").exists():
        raise RuntimeError(
            "No .git directory found in the stored repo. "
            "Only repositories cloned from GitHub support branch/PR creation."
        )

    git_repo = GitRepo(str(repo_root))

    try:
        remote_url = git_repo.remotes["origin"].url
    except (IndexError, KeyError, AttributeError):
        remote_url = ""

    provider = _detect_provider(remote_url)
    push_url = _inject_credentials(remote_url, provider, token=token)
    sanitised_url = _sanitise_url(remote_url)

    default_branch = "main"
    try:
        head_ref = git_repo.git.symbolic_ref("refs/remotes/origin/HEAD")
        default_branch = head_ref.split("/")[-1]
    except Exception:
        try:
            default_branch = git_repo.active_branch.name
        except Exception:
            pass

    # Create / reset branch safely and idempotently
    try:
        if git_repo.head.is_valid() and not git_repo.head.is_detached:
            if git_repo.active_branch.name == branch_name:
                try:
                    git_repo.git.checkout(default_branch)
                except Exception:
                    pass

        if branch_name in [b.name for b in git_repo.branches]:
            try:
                git_repo.git.branch("-D", branch_name)
            except Exception:
                pass

        try:
            git_repo.git.checkout("-B", branch_name, f"origin/{default_branch}")
        except Exception:
            try:
                git_repo.git.checkout("-B", branch_name, default_branch)
            except Exception:
                git_repo.git.checkout("-B", branch_name)
    except Exception as exc:
        raise RuntimeError(f"Could not create branch '{branch_name}': {exc}")

    # Copy README.md to repo root
    readme_src = docs_dir / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, repo_root / "README.md")

    # Copy all doc files into repo_root / "docs"
    target_docs = repo_root / "docs"
    target_docs.mkdir(parents=True, exist_ok=True)
    for doc_file in docs_dir.glob("*"):
        if doc_file.is_file():
            shutil.copy2(doc_file, target_docs / doc_file.name)

    git_repo.git.add("-A")

    author = Actor(author_name, author_email)
    commit = git_repo.index.commit(
        commit_message,
        author=author,
        committer=author,
    )
    commit_sha = commit.hexsha

    try:
        git_repo.git.push(push_url, f"{branch_name}:{branch_name}", "--force-with-lease")
    except Exception as exc:
        clean_err = sanitize_sensitive_text(str(exc))
        raise RuntimeError(
            f"Push failed for branch '{branch_name}' to {sanitised_url}: {clean_err}"
        ) from None

    logger.info(
        "Pushed docs branch '%s' (commit %s) to %s [%s]",
        branch_name,
        commit_sha[:8],
        sanitised_url,
        provider,
    )

    return BranchResult(
        branch_name=branch_name,
        commit_sha=commit_sha,
        remote_url=sanitised_url,
        provider=provider,
    )


def create_or_checkout_branch(repo_path: str | Path, branch_name: str) -> dict:
    """
    Idempotently checkout or create branch_name in the repository at repo_path.
    If the branch already exists, it safely checks it out using checkout -B
    without collision or already-exists errors.
    """
    try:
        from git import Repo as GitRepo
    except ImportError:
        raise RuntimeError("gitpython is not installed")

    git_repo = GitRepo(str(repo_path))
    try:
        git_repo.git.checkout("-B", branch_name)
        return {"success": True, "branch": branch_name}
    except Exception as exc:
        logger.warning("Could not checkout branch %s: %s", branch_name, exc)
        return {"success": False, "error": str(exc)}

