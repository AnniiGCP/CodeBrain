"""
backend/errordetection/scanner.py
---------------------------------
Lightweight, authentic error-detection scanner.
Scans repository files and AST symbols for genuine errors and smells.
Guarantees:
  1. Zero fabricated/hallucinated errors.
  2. Line numbers strictly validated against disk source files.
  3. Clean separation between ERRORS, WARNINGS, RECOMMENDATIONS, and AI INSIGHTS.
  4. Best-practice suggestions (e.g. print vs logging) are RECOMMENDATIONS, NOT errors.
  5. Deduplication via cryptographic fingerprinting.
  6. Returns 'No errors detected.' when no genuine violations exist.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

# ── RULE DEFINITIONS ──────────────────────────────────────────────────────────
# Format: (rule_id, category, severity, pattern, message)
# Categories: "ERROR" | "WARNING" | "RECOMMENDATION"

_PYTHON_RULES = [
    (
        "PY001",
        "ERROR",
        "error",
        re.compile(r"\bexcept\s*:", re.MULTILINE),
        "Bare 'except:' clause catches all exceptions including SystemExit.",
    ),
    (
        "PY003",
        "WARNING",
        "warning",
        re.compile(r"\beval\s*\(", re.MULTILINE),
        "Use of eval() introduces potential arbitrary code execution risk.",
    ),
    (
        "PY004",
        "WARNING",
        "warning",
        re.compile(r"\bexec\s*\(", re.MULTILINE),
        "Use of exec() introduces potential arbitrary code execution risk.",
    ),
    (
        "PY007",
        "WARNING",
        "warning",
        re.compile(r"\bpassword\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
        "Hard-coded password detected in source code.",
    ),
    (
        "PY008",
        "WARNING",
        "warning",
        re.compile(r"def\s+\w+\s*\([^)]*\)\s*:\s*\n\s*pass\s*$", re.MULTILINE),
        "Empty function body with only 'pass' placeholder.",
    ),
    # Recommendations (style / best practice — NOT errors)
    (
        "PY_REC001",
        "RECOMMENDATION",
        "info",
        re.compile(r"\bprint\s*\(", re.MULTILINE),
        "Consider using structured logging instead of print() in production.",
    ),
    (
        "PY_REC002",
        "RECOMMENDATION",
        "info",
        re.compile(r"#\s*TODO", re.IGNORECASE | re.MULTILINE),
        "TODO comment found — track task in backlog.",
    ),
    (
        "PY_REC003",
        "RECOMMENDATION",
        "info",
        re.compile(r"#\s*FIXME", re.IGNORECASE | re.MULTILINE),
        "FIXME comment found — needs review.",
    ),
]

_JS_RULES = [
    (
        "JS002",
        "ERROR",
        "error",
        re.compile(r"\beval\s*\(", re.MULTILINE),
        "Use of eval() introduces script injection risk.",
    ),
    (
        "JS005",
        "WARNING",
        "warning",
        re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
        "Hard-coded password detected in JavaScript/TypeScript file.",
    ),
    (
        "JS006",
        "WARNING",
        "warning",
        re.compile(r"\bdebugger\b", re.MULTILINE),
        "debugger statement left in production code.",
    ),
    # Recommendations
    (
        "JS_REC001",
        "RECOMMENDATION",
        "info",
        re.compile(r"\bconsole\.log\s*\(", re.MULTILINE),
        "Consider using structured logger instead of console.log().",
    ),
    (
        "JS_REC002",
        "RECOMMENDATION",
        "info",
        re.compile(r"//\s*TODO", re.IGNORECASE | re.MULTILINE),
        "TODO comment found — track in backlog.",
    ),
]

_GENERAL_RULES = [
    (
        "GEN001",
        "WARNING",
        "warning",
        re.compile(r"(secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE),
        "Potential hardcoded secret or API key credential detected.",
    ),
]


def _get_rules_for_language(language: Optional[str]):
    lang = (language or "").lower()
    if lang == "python":
        return _PYTHON_RULES + _GENERAL_RULES
    elif lang in ("javascript", "typescript", "vue", "svelte"):
        return _JS_RULES + _GENERAL_RULES
    return _GENERAL_RULES


def _generate_fingerprint(source: str, rule: str, file_path: str, line: Optional[int], column: Optional[int], message: str) -> str:
    raw = f"{source}:{rule}:{file_path}:{line or 0}:{column or 0}:{message}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_test_or_benchmark_file(file_path: str) -> bool:
    """Return True if the file path indicates a test, benchmark, or mock file."""
    norm = file_path.replace("\\", "/").lower()
    parts = norm.split("/")
    filename = parts[-1]
    if any(p in ("tests", "test", "testing", "benchmarks", "benchmark", "mocks", "mock") for p in parts[:-1]):
        return True
    if filename.startswith("test_") or filename.endswith("_test.py") or filename in ("hits.py", "benchmark.py"):
        return True
    return False


def _is_code_file(file_path: str, language: Optional[str]) -> bool:
    """Check if the file is an actual source code file rather than docs/markdown/config."""
    norm = file_path.replace("\\", "/").lower()
    if norm.endswith((".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock")):
        return False
    lang = (language or "").lower()
    return lang in ("python", "javascript", "typescript", "vue", "svelte") or norm.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))


def _validate_issue_against_disk(disk_path: Path, issue: dict, pattern: Optional[re.Pattern] = None) -> bool:
    """
    Validates that:
    1. File exists on disk.
    2. Line number is within valid line count.
    3. The line on disk strictly contains the issue's pattern.
    """
    if not disk_path.exists():
        return False
    try:
        lines = disk_path.read_text(encoding="utf-8", errors="replace").splitlines()
        target_line = issue.get("line")
        if target_line is None:
            return True
        if target_line < 1 or target_line > len(lines):
            logger.warning(
                "Discarding hallucinated issue: line %d exceeds file line count %d for %s",
                target_line, len(lines), disk_path
            )
            return False

        # Verify referenced code line exists and matches pattern
        actual_code_line = lines[target_line - 1].strip()
        if pattern and not pattern.search(actual_code_line):
            logger.warning(
                "Pattern mismatch on disk for %s:%d (found %r, expected %s). Discarding.",
                disk_path, target_line, actual_code_line, issue.get("rule_id")
            )
            return False

        issue["code"] = actual_code_line
        return True
    except Exception as exc:
        logger.warning("Failed disk validation for %s: %s", disk_path, exc)
        return False


def _check_file_syntax(disk_path: Path, rel_path: str, language: Optional[str]) -> List[dict]:
    """Validate file syntax using genuine AST parsers (e.g. Python ast)."""
    syntax_issues: List[dict] = []
    if not disk_path.exists():
        return []

    if (language or "").lower() == "python" or rel_path.endswith(".py"):
        import ast
        try:
            content = disk_path.read_text(encoding="utf-8", errors="replace")
            ast.parse(content, filename=rel_path)
        except SyntaxError as syn_err:
            stack = f'File "{rel_path}", line {syn_err.lineno}, col {syn_err.offset}\n{syn_err.text or ""}'
            syntax_issues.append({
                "symbol_id": None,
                "symbol_name": None,
                "symbol_type": "file",
                "file_path": rel_path,
                "language": "python",
                "rule_id": "SYNTAX_ERROR",
                "source": "parser",
                "category": "ERROR",
                "severity": "error",
                "message": f"Parser Error (SyntaxError): {syn_err.msg}",
                "line": syn_err.lineno,
                "column": syn_err.offset,
                "code": (syn_err.text or "").strip(),
                "stack_trace": stack,
                "evidence": f"Python ast parser failed at line {syn_err.lineno}",
            })
        except Exception as exc:
            syntax_issues.append({
                "symbol_id": None,
                "symbol_name": None,
                "symbol_type": "file",
                "file_path": rel_path,
                "language": "python",
                "rule_id": "PARSER_ERROR",
                "source": "parser",
                "category": "ERROR",
                "severity": "error",
                "message": f"Parser Error: {str(exc)}",
                "line": 1,
                "column": None,
                "code": "",
                "stack_trace": str(exc),
                "evidence": str(exc),
            })

    return syntax_issues


def detect_errors(repo_id: str, db: "Session") -> dict:
    """
    Scan a repository for genuine code issues, parser errors, and smells.
    Directly scans actual files on disk line-by-line for 100% accurate line numbers.
    Separates ERRORS, WARNINGS, RECOMMENDATIONS, and AI INSIGHTS.
    NEVER fabricates synthetic errors.
    """
    from models import Repo, RepoFile, Symbol

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if repo is None:
        raise ValueError(f"Repo {repo_id!r} not found")

    storage_root = STORAGE_ROOT / repo_id
    raw_candidates: List[Tuple[dict, Optional[re.Pattern]]] = []

    # 1. Genuine Parser / Syntax Errors across all repo files
    files = db.query(RepoFile).filter(RepoFile.repo_id == repo_id).all()
    file_disk_map: Dict[str, Path] = {}
    for rf in files:
        disk_p = storage_root / rf.path
        if not disk_p.exists() and storage_root.exists() and storage_root.is_dir():
            for child in storage_root.iterdir():
                if child.is_dir() and (child / rf.path).exists():
                    disk_p = child / rf.path
                    break
        file_disk_map[rf.path] = disk_p
        syntax_errs = _check_file_syntax(disk_p, rf.path, rf.language)
        for serr in syntax_errs:
            raw_candidates.append((serr, None))

    # 2. Genuine static analysis smells scanned directly against files on disk
    for rf in files:
        disk_p = file_disk_map.get(rf.path, storage_root / rf.path)
        if not disk_p.exists() or not disk_p.is_file():
            continue

        # Skip non-code files (markdown, docs, configs) for code rules
        if not _is_code_file(rf.path, rf.language):
            continue

        rules = _get_rules_for_language(rf.language)
        is_test_file = _is_test_or_benchmark_file(rf.path)

        try:
            lines = disk_p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:
            logger.warning("Could not read disk file %s for scanning: %s", disk_p, exc)
            continue

        file_rule_seen: set[str] = set()
        for line_idx, line_text in enumerate(lines, 1):
            for rule_id, category, severity, pattern, message in rules:
                # In test or benchmark files, skip print() logging suggestions
                if is_test_file and rule_id in ("PY_REC001", "JS_REC001"):
                    continue

                # Don't spam repetitive recommendations for the same file
                if category == "RECOMMENDATION" and rule_id in file_rule_seen:
                    continue

                m = pattern.search(line_text)
                if m:
                    file_rule_seen.add(rule_id)
                    col_offset = m.start() + 1
                    issue_dict = {
                        "symbol_id": None,
                        "symbol_name": None,
                        "symbol_type": "line",
                        "file_path": rf.path,
                        "language": rf.language or ("python" if rf.path.endswith(".py") else "javascript"),
                        "rule_id": rule_id,
                        "source": "static_analysis",
                        "category": category,
                        "severity": severity,
                        "message": message,
                        "line": line_idx,
                        "column": col_offset,
                        "code": line_text.strip(),
                        "stack_trace": None,
                        "evidence": f"Rule {rule_id} detected on disk line {line_idx}:{col_offset} - '{line_text.strip()}'",
                    }
                    raw_candidates.append((issue_dict, pattern))

    # 3. Deduplicate and Validate against actual disk files
    seen_fingerprints = set()
    validated_errors: List[dict] = []
    validated_warnings: List[dict] = []
    validated_recommendations: List[dict] = []

    for item, pattern in raw_candidates:
        disk_file = file_disk_map.get(item["file_path"], storage_root / item["file_path"])
        if not _validate_issue_against_disk(disk_file, item, pattern):
            continue

        fingerprint = _generate_fingerprint(
            item["source"], item["rule_id"], item["file_path"],
            item["line"], item["column"], item["message"]
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        item["fingerprint"] = fingerprint

        cat = item.get("category", "WARNING")
        if cat == "ERROR":
            validated_errors.append(item)
        elif cat == "WARNING":
            validated_warnings.append(item)
        elif cat == "RECOMMENDATION":
            validated_recommendations.append(item)

    # Combine actionable issues (Errors + Warnings) for ErrorReport tracking
    actionable_issues = validated_errors + validated_warnings

    status_message = (
        f"{len(validated_errors)} error(s) and {len(validated_warnings)} warning(s) detected."
        if (validated_errors or validated_warnings)
        else "No errors detected."
    )

    logger.info(
        "Error scan complete for %s: %d errors, %d warnings, %d recommendations. Clean state: %s",
        repo_id, len(validated_errors), len(validated_warnings), len(validated_recommendations), not actionable_issues
    )

    return {
        "repo_id": repo_id,
        "total_symbols_scanned": len(files),
        "total_issues": len(actionable_issues),
        "total_errors": len(validated_errors),
        "total_warnings": len(validated_warnings),
        "total_recommendations": len(validated_recommendations),
        "message": status_message,
        "errors": validated_errors,
        "warnings": validated_warnings,
        "recommendations": validated_recommendations,
        "ai_insights": [],
        "issues": actionable_issues,  # used by pipeline to persist ErrorReports
    }
