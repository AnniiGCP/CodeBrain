"""
codefix/patch_safety.py
-----------------------
Static patch format and safety validation, containment checking,
and safe atomic file application without code execution or sandbox testing.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALIDATION_SKIPPED_NOTICE = (
    "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change."
)


def _is_within_repo(repo_root: Path, target_path: Path) -> bool:
    """Check that target_path is contained strictly within repo_root."""
    try:
        resolved_root = repo_root.resolve()
        resolved_target = target_path.resolve()
        resolved_target.relative_to(resolved_root)
        return True
    except (ValueError, RuntimeError):
        return False


def _parse_diff_metadata(diff_text: str) -> dict[str, Any]:
    """Extract files, hunks, and line counts from unified diff text."""
    lines = diff_text.splitlines()
    files: list[str] = []
    added = 0
    deleted = 0
    has_headers = False
    has_hunks = False

    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            has_headers = True
            if line.startswith("+++ "):
                raw = line[4:].strip().split("\t")[0]
                if raw.startswith("b/"):
                    raw = raw[2:]
                if raw and raw not in ("/dev/null", "b"):
                    files.append(raw)
        elif line.startswith("@@ "):
            has_hunks = True
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1

    return {
        "files": files,
        "has_headers": has_headers,
        "has_hunks": has_hunks,
        "added": added,
        "deleted": deleted,
    }


def validate_patch_format_and_safety(
    repo_root: Path | str,
    target_file_path: str,
    diff_text: str | None = None,
    patched_content: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Validate patch format, repository workspace containment, and file safety
    without executing any code, test commands, or compilers.

    Returns:
        (is_valid, error_message, details_dict)
    """
    root = Path(repo_root)
    if not root.exists() or not root.is_dir():
        return False, f"Repository root does not exist or is not a directory: {repo_root}", {}

    has_diff = bool(diff_text and diff_text.strip())
    has_content = bool(patched_content and patched_content.strip())

    # 1. Reject empty patches
    if not has_diff and not has_content:
        return False, "Patch is empty. Provide a valid unified diff or full replacement content.", {}

    # 2. Reject paths escaping repository root
    target_clean = (target_file_path or "").strip().replace("\\", "/")
    if not target_clean:
        return False, "Target file path is required.", {}

    if ".." in target_clean.split("/"):
        return False, f"Security violation: path traversal detected in '{target_file_path}'", {}

    target_candidate = root / target_clean
    if not _is_within_repo(root, target_candidate):
        return False, f"Security violation: target file '{target_file_path}' escapes repository workspace.", {}

    # 3. Format validation for unified diffs
    if has_diff:
        meta = _parse_diff_metadata(diff_text or "")
        if not meta["has_headers"] and not meta["has_hunks"]:
            return False, "Unsupported patch format: missing unified diff headers (--- and +++) and @@ hunks.", {}

        # Verify any file paths mentioned inside the diff also stay inside repo
        for f in meta["files"]:
            f_clean = f.strip().replace("\\", "/")
            if ".." in f_clean.split("/"):
                return False, f"Security violation: path traversal in diff header '{f}'", {}
            f_path = root / f_clean
            if not _is_within_repo(root, f_path):
                return False, f"Security violation: diff references file outside repository: '{f}'", {}

        # 4. Check target file existence or alternative path match
        target_path = target_candidate
        if not target_path.exists():
            matches = list(root.rglob(Path(target_clean).name))
            if matches:
                target_path = matches[0]
            else:
                # If creating new file, verify parent directory is writable/creatable
                pass

        return True, "", {
            "target_path": str(target_path),
            "files": meta["files"] or [target_clean],
            "lines_added": meta["added"],
            "lines_deleted": meta["deleted"],
            "diff_format": "unified_diff",
        }

    # 4. Format validation for full file replacement
    return True, "", {
        "target_path": str(target_candidate),
        "files": [target_clean],
        "lines_added": len((patched_content or "").splitlines()),
        "lines_deleted": 0,
        "diff_format": "full_content",
    }


def _apply_unified_diff_pure_python(
    repo_root: Path,
    diff_text: str,
    target_file_hint: str | None = None,
) -> tuple[bool, str, list[str]]:
    """
    Apply a unified diff using pure Python logic with fallback hunk matching.
    Returns (success, error_message, list_of_modified_relative_files).
    """
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

    if not file_diffs and target_file_hint:
        # Diff may just be raw hunks without --- / +++ headers
        file_diffs.append({"orig": target_file_hint, "target": target_file_hint, "hunk_text": lines})

    if not file_diffs:
        return False, "No valid unified diff hunks found.", []

    modified_files: list[str] = []

    for fd in file_diffs:
        target_name = fd["target"] or fd["orig"] or target_file_hint
        if not target_name:
            continue

        target_path = repo_root / target_name
        if not target_path.exists():
            matches = list(repo_root.rglob(Path(target_name).name))
            if matches:
                target_path = matches[0]
            else:
                return False, f"Target file not found in repo: {target_name}", []

        try:
            orig_text = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return False, f"Could not read {target_name}: {exc}", []

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
            return False, f"No @@ hunks found for {target_name}", []

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
                return False, f"Could not locate matching context in {target_name} for hunk @@ -{old_start}...", []

            eol = "\r\n" if orig_text.count("\r\n") > orig_text.count("\n") // 2 else "\n"
            formatted_new = [
                (l.rstrip("\r\n") + eol) for l in new_hunk_lines
            ]
            result_lines[matched_pos : matched_pos + n] = formatted_new

        try:
            target_path.write_text("".join(result_lines), encoding="utf-8")
            try:
                rel = str(target_path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
            except Exception:
                rel = target_name
            modified_files.append(rel)
        except Exception as exc:
            return False, f"Could not write patched content to {target_name}: {exc}", []

    return True, "", modified_files


def apply_patch_safely(
    repo_root: Path | str,
    target_file_path: str,
    diff_text: str | None = None,
    patched_content: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Safely apply a patch (diff or full file) without executing any code.
    Maintains in-memory backups for rollback on conflict or write failure.
    Confirms that the target file exists, was written, and differs from original.

    Returns:
        (success, error_message, result_dict)
    """
    root = Path(repo_root)
    valid, err_msg, details = validate_patch_format_and_safety(
        repo_root=root,
        target_file_path=target_file_path,
        diff_text=diff_text,
        patched_content=patched_content,
    )
    if not valid:
        return False, err_msg, {}

    target_candidate = root / target_file_path.strip().replace("\\", "/")
    if not target_candidate.exists():
        matches = list(root.rglob(Path(target_file_path).name))
        if matches:
            target_candidate = matches[0]

    # In-memory backup for rollback
    backups: dict[Path, str] = {}
    if target_candidate.exists():
        try:
            backups[target_candidate] = target_candidate.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return False, f"Failed to read original file '{target_file_path}': {exc}", {}

    has_diff = bool(diff_text and diff_text.strip())

    try:
        if has_diff:
            ok, apply_err, mod_files = _apply_unified_diff_pure_python(
                repo_root=root,
                diff_text=diff_text or "",
                target_file_hint=target_file_path,
            )
            if not ok:
                # Rollback
                for fpath, orig_content in backups.items():
                    fpath.write_text(orig_content, encoding="utf-8")
                return False, apply_err, {}
            changed_files = mod_files or [target_file_path]
        else:
            # Full content replacement
            target_candidate.parent.mkdir(parents=True, exist_ok=True)
            target_candidate.write_text(patched_content or "", encoding="utf-8")
            try:
                rel = str(target_candidate.resolve().relative_to(root.resolve())).replace("\\", "/")
            except Exception:
                rel = target_file_path
            changed_files = [rel]

        # Confirm write took effect
        for cf in changed_files:
            cf_path = root / cf
            if not cf_path.exists():
                for fpath, orig_content in backups.items():
                    fpath.write_text(orig_content, encoding="utf-8")
                return False, f"Write confirmation failed: modified file '{cf}' does not exist on disk.", {}

            new_text = cf_path.read_text(encoding="utf-8", errors="replace")
            orig_text = backups.get(cf_path)
            if orig_text is not None and new_text == orig_text:
                # No content change occurred
                return False, f"Patch applied but produced zero content change in '{cf}'.", {}

        return True, "", {
            "changed_files": changed_files,
            "lines_added": details.get("lines_added", 0),
            "lines_deleted": details.get("lines_deleted", 0),
            "diff": diff_text,
            "validation_status": "NOT_RUN",
            "validation_skipped": True,
            "validation_notice": VALIDATION_SKIPPED_NOTICE,
        }

    except Exception as exc:
        logger.exception("Unexpected error while applying patch to %s: %s", target_file_path, exc)
        for fpath, orig_content in backups.items():
            try:
                fpath.write_text(orig_content, encoding="utf-8")
            except Exception:
                pass
        return False, f"Unexpected error during patch application: {exc}", {}
