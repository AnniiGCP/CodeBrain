"""
errordetection/suggestion.py
-----------------------------
For each ErrorReport row, generates:
  1. A short AI explanation (reuses codefix/explainer.py prompt style)
  2. A proposed unified diff fix (reuses codefix/fixer.py)

Called automatically from the pipeline after detect_errors() saves rows.
Runs each issue in its own try/except so one failure doesn't block others.

Public API
----------
generate_suggestions_for_repo(repo_id, db) -> None
generate_suggestion_for_report(report_id, db) -> None   (single, used by retry)
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Only fix severity levels that benefit from an AI fix (skip pure "info" TODOs etc.)
_FIXABLE_SEVERITIES = {"error", "warning"}
# Rules we intentionally skip fix generation for (too noisy / no code change needed)
_SKIP_FIX_RULES = {"PY005", "PY006", "JS003", "JS004"}  # TODO / FIXME markers


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_EXPLAIN_SYSTEM = """\
You are a senior security and code-quality reviewer.
Given an issue found in a code snippet, write a short, clear explanation (max 80 words):
- What the problem is
- Why it matters (security / reliability / maintainability)
- One sentence on how to fix it
Use plain English. No bullet points. No markdown headers.
"""

_EXPLAIN_TEMPLATE = """\
Rule: {rule_id}
Severity: {severity}
Issue: {message}
File: {file_path}  Language: {language}

Affected code snippet:
```
{source_code}
```

Explain the issue briefly.
"""

_FIX_ISSUE_TEMPLATE = """\
Fix the following code quality issue:

Rule: {rule_id}
Issue: {message}
File: {file_path}  Language: {language}

Affected symbol source:
```
{source_code}
```

Produce a minimal unified diff that fixes ONLY this specific issue.
"""


def _get_symbol_source(report, db) -> str | None:
    """Return the source code of a Symbol, or fallback to file content on disk."""
    if getattr(report, "symbol_id", None) is not None:
        try:
            from models import Symbol
            sym = db.query(Symbol).filter(Symbol.id == report.symbol_id).first()
            if sym and sym.source_code:
                return sym.source_code
        except Exception:
            pass

    try:
        from routers.errors import _find_repo_root
        root = _find_repo_root(report.repo_id)
        if root:
            target = root / report.file_path
            if not target.exists():
                matches = list(root.rglob(Path(report.file_path).name))
                if matches:
                    target = matches[0]
            if target.exists():
                return target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return None


def _generate_explanation(report, source_code: str, db) -> str:
    """Call centralized AI router to get a short explanation for this issue."""
    from ai.router import route_chat

    user_msg = _EXPLAIN_TEMPLATE.format(
        rule_id=report.rule_id,
        severity=report.severity,
        message=report.message,
        file_path=report.file_path,
        language=report.language or "unknown",
        source_code=source_code[:800],  # cap to keep prompt small
    )
    messages = [
        {"role": "system", "content": _EXPLAIN_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    try:
        return route_chat(messages, task_type="error_analysis", max_tokens=200, temperature=0.3)
    except Exception as exc:
        logger.warning("Error explanation generation via router failed: %s", exc)
        from docgen.groq_client import call_groq
        return call_groq(messages, max_tokens=200, temperature=0.3)


def _generate_fix_diff(report, source_code: str, db) -> dict:
    """
    Generate unified diff fix for ErrorReport using central issue-fixing router.
    Returns dict with diff, model_used, provider, fix_attribution, attempts.
    """
    if getattr(report, "symbol_id", None) is not None:
        try:
            from codefix.fixer import generate_fix
            result = generate_fix(
                symbol_id=report.symbol_id,
                issue_description=f"{report.rule_id}: {report.message}",
                db=db,
            )
            return result
        except Exception as exc:
            logger.warning("generate_fix via symbol_id failed (%s), trying direct prompt", exc)

    # Fallback: direct LLM call with the fix template via central issue-fixing router
    from codefix.fixer import _SYSTEM as FIX_SYSTEM
    from ai.issue_fix_router import route_issue_fix

    user_msg = _FIX_ISSUE_TEMPLATE.format(
        rule_id=report.rule_id,
        message=report.message,
        file_path=report.file_path,
        language=report.language or "unknown",
        source_code=source_code[:2500],
    )
    messages = [
        {"role": "system", "content": FIX_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    fix_res = route_issue_fix(
        messages=messages,
        expected_file_path=report.file_path,
        source_code=source_code,
        temperature=0.05,
        max_tokens=2048,
    )

    return {
        "diff": fix_res.diff,
        "model_used": fix_res.model,
        "model_display_name": fix_res.model_display_name,
        "provider": fix_res.provider,
        "fallback_used": fix_res.fallback_used,
        "fix_attribution": fix_res.fix_attribution,
        "attempts": fix_res.attempts,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_suggestion_for_report(report_id: str, db) -> None:
    """
    Generate explanation + fix diff for a single ErrorReport.
    Updates the row in-place.  Idempotent — skips if already READY/APPLIED.
    """
    import json
    from models import ErrorReport

    report = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if report is None:
        logger.warning("generate_suggestion_for_report: report %s not found", report_id)
        return

    if report.fix_status in ("READY", "APPLIED", "REJECTED"):
        return  # already done

    if report.rule_id in _SKIP_FIX_RULES or report.severity not in _FIXABLE_SEVERITIES:
        # For info/TODO issues: generate explanation only, mark READY with no diff
        try:
            source_code = _get_symbol_source(report, db) or ""
            if source_code:
                report.explanation = _generate_explanation(report, source_code, db)
        except Exception as exc:
            logger.warning("Explanation generation skipped for %s: %s", report_id, exc)
        report.fix_status = "READY"
        db.commit()
        return

    report.fix_status = "GENERATING"
    db.commit()

    try:
        source_code = _get_symbol_source(report, db) or ""

        # 1. Explanation
        if source_code:
            try:
                report.explanation = _generate_explanation(report, source_code, db)
            except Exception as exc:
                logger.warning("Explanation failed for report %s: %s", report_id, exc)

        # 2. Fix diff
        if source_code:
            fix_data = _generate_fix_diff(report, source_code, db)
            report.suggested_fix = fix_data.get("diff", "")
            report.fix_model = fix_data.get("model_used")
            report.fix_provider = fix_data.get("provider")
            report.fix_attribution = fix_data.get("fix_attribution")
            attempts = fix_data.get("attempts", [])
            report.fix_attempts = json.dumps(attempts) if attempts else None

        report.fix_status = "READY"
        report.fix_error = None
        db.commit()
        logger.info("Suggestion ready for error report %s (%s) via %s", report_id, report.rule_id, report.fix_provider)

    except Exception as exc:
        logger.exception("Failed to generate suggestion for report %s", report_id)
        report.fix_status = "FAILED"
        report.fix_error = str(exc)
        db.commit()


def generate_suggestions_for_repo(repo_id: str, db) -> None:
    """
    Generate suggestions for ALL pending ErrorReports of a repo.
    Runs synchronously — call from a background thread.
    """
    from models import ErrorReport

    pending = (
        db.query(ErrorReport)
        .filter(
            ErrorReport.repo_id == repo_id,
            ErrorReport.fix_status.in_(["PENDING", "FAILED"]),
        )
        .all()
    )

    logger.info("Generating suggestions for %d error reports in repo %s", len(pending), repo_id)
    for report in pending:
        try:
            generate_suggestion_for_report(report.id, db)
        except Exception as exc:
            logger.exception("Suggestion generation crashed for report %s: %s", report.id, exc)
