"""
backend/docgen/validator.py
--------------------------
Authoritative Central Validator for CodeBrain Universal Documentation Suite.
Enforces the immutable 16-section contract, section-specific detail requirements,
factual grounding, diagram syntax integrity, and server-authoritative completion gate.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docgen.schema import (
    CANONICAL_SECTIONS_COUNT,
    CANONICAL_SECTION_BY_ID,
    DOCUMENTATION_SECTIONS,
    DocSection,
    LEGACY_FILENAMES_BY_ID,
    SECTIONS_META,
    resolve_canonical_filename,
)

logger = logging.getLogger(__name__)

# Banned placeholder tokens that indicate fake or stubbed generation
PLACEHOLDER_TOKENS = [
    "lorem ipsum",
    "todo: implement",
    "tbd",
    "placeholder for section",
    "insert content here",
    "section content goes here",
    "as an ai language model",
]

# Section-specific keyword requirements for grounded technical depth
SECTION_GROUNDING_KEYWORDS: Dict[int, List[List[str]]] = {
    1: [["overview", "project", "purpose"], ["architecture", "features", "scope", "entry"]],
    2: [["technology", "stack", "language", "framework"], ["dependencies", "runtime", "manifest", "library"]],
    3: [["structure", "directory", "hierarchy", "tree"], ["module", "file", "path", "organization"]],
    4: [["architecture", "topology", "system"], ["component", "data flow", "interaction", "layer"]],
    5: [["module", "component", "subsystem"], ["responsibility", "boundary", "dependency", "interface"]],
    6: [["class", "function", "symbol", "method", "ast"], ["signature", "routine", "handler", "call"]],
    7: [["api", "endpoint", "route", "interface"], ["request", "response", "handler", "stateless", "library", "cli"]],
    8: [["database", "data model", "entity", "schema"], ["persistence", "table", "column", "stateless", "ephemeral", "model"]],
    9: [["relationship", "cardinality", "foreign key", "association"], ["entity", "relational", "er", "data flow", "component"]],
    10: [["dependencies", "package", "manifest"], ["runtime", "ecosystem", "version", "library"]],
    11: [["configuration", "environment", "variable"], ["runtime", "setting", "default", "secret"]],
    12: [["test", "testing", "suite", "framework"], ["verification", "assertion", "coverage", "automated", "runner", "manual"]],
    13: [["security", "authentication", "authorization"], ["vulnerability", "protection", "access", "secret", "input"]],
    14: [["ci/cd", "ci", "pipeline", "workflow"], ["action", "stage", "build", "deployment", "automation", "manual"]],
    15: [["deployment", "container", "infrastructure", "docker"], ["runtime", "host", "service", "environment", "topology"]],
    16: [["setup", "developer", "guide", "onboarding"], ["installation", "prerequisite", "command", "run", "execution"]],
}


@dataclass
class SectionValidationResult:
    section_id: int
    title: str
    is_valid: bool
    status: str  # "COMPLETE" | "FAILED" | "NEEDS_REVIEW"
    word_count: int
    char_count: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    has_diagram: bool = False
    is_absence_documented: bool = False


@dataclass
class SuiteIntegrityReport:
    is_complete: bool
    status: str  # "COMPLETE" | "PARTIAL" | "FAILED"
    total_sections: int = CANONICAL_SECTIONS_COUNT
    valid_sections_count: int = 0
    missing_section_ids: List[int] = field(default_factory=list)
    invalid_section_ids: List[int] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    section_reports: Dict[int, SectionValidationResult] = field(default_factory=dict)
    master_document_valid: bool = False


def validate_mermaid_syntax(chart_code: str) -> Tuple[bool, str]:
    """Validates Mermaid diagram syntax."""
    if not chart_code or not chart_code.strip():
        return False, "Empty Mermaid chart code."
    lines = [l.strip() for l in chart_code.strip().splitlines() if l.strip() and not l.strip().startswith("%%")]
    if not lines:
        return False, "Mermaid code contains only comments or whitespace."

    valid_headers = (
        "graph td", "graph lr", "graph tb", "graph rl",
        "flowchart td", "flowchart lr", "flowchart tb", "flowchart rl",
        "sequencediagram", "classdiagram", "erdiagram",
        "statediagram", "statediagram-v2", "gantt", "pie", "gitgraph", "quadrantchart",
        "c4context", "mindmap", "timeline", "block"
    )
    first_line = lines[0].lower().replace(" ", "")
    has_valid_header = any(first_line.startswith(h.replace(" ", "")) for h in valid_headers)
    if not has_valid_header:
        return False, f"Invalid or unrecognized Mermaid diagram header: '{lines[0]}'."

    if len(lines) < 2:
        return False, "Mermaid diagram is incomplete (fewer than 2 statements)."

    for opener, closer in [("[", "]"), ("(", ")"), ("{", "}")]:
        if chart_code.count(opener) != chart_code.count(closer):
            return False, f"Unbalanced brackets in Mermaid diagram: '{opener}' vs '{closer}'."

    if chart_code.count('"') % 2 != 0:
        return False, "Unbalanced double quotes in Mermaid diagram."

    return True, ""


def validate_section_content(
    section_id: int,
    title: str,
    content: str,
    graph: Any = None,
    display_number: Optional[int] = None,
) -> SectionValidationResult:
    """
    Validates the content of a single documentation section against its canonical contract.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if section_id not in CANONICAL_SECTION_BY_ID:
        return SectionValidationResult(
            section_id=section_id,
            title=title,
            is_valid=False,
            status="FAILED",
            word_count=0,
            char_count=0,
            errors=[f"Section ID {section_id} is not one of the canonical 16 section IDs."],
        )

    canonical_meta = CANONICAL_SECTION_BY_ID[section_id]
    if title != canonical_meta["title"]:
        errors.append(
            f"Section title mismatch for ID {section_id}: expected '{canonical_meta['title']}', got '{title}'."
        )

    clean_content = (content or "").strip()
    char_count = len(clean_content)
    word_count = len(clean_content.split())

    if not clean_content:
        return SectionValidationResult(
            section_id=section_id,
            title=canonical_meta["title"],
            is_valid=False,
            status="FAILED",
            word_count=0,
            char_count=0,
            errors=[f"Section {section_id} ({canonical_meta['title']}) is empty."],
        )

    # Minimum substantive length check (must contain real prose, not just a 1-line stub)
    if char_count < 140:
        errors.append(
            f"Section {section_id} is too short ({char_count} chars). Substantive technical detail is required."
        )

    # Check for placeholder text
    lower_content = clean_content.lower()
    for token in PLACEHOLDER_TOKENS:
        if token in lower_content:
            errors.append(f"Section {section_id} contains placeholder token: '{token}'.")

    # Check for incomplete / truncated code fences
    fence_count = clean_content.count("```")
    if fence_count % 2 != 0:
        errors.append(f"Section {section_id} has unclosed markdown code fence (``` count is {fence_count}).")

    # Check Mermaid diagrams if present
    mermaid_pattern = re.compile(r'```mermaid\s*([\s\S]*?)\s*```', re.IGNORECASE)
    has_diagram = bool(mermaid_pattern.search(clean_content))
    for m in mermaid_pattern.finditer(clean_content):
        diag_body = m.group(1).strip()
        is_diag_valid, diag_err = validate_mermaid_syntax(diag_body)
        if not is_diag_valid:
            errors.append(f"Section {section_id} contains invalid Mermaid syntax: {diag_err}")

    # Check section grounding keywords
    required_groups = SECTION_GROUNDING_KEYWORDS.get(section_id, [])
    for group in required_groups:
        if not any(kw in lower_content for kw in group):
            warnings.append(
                f"Section {section_id} does not contain standard terminology from: {group}"
            )

    # Check honest absence handling for specific sections
    is_absence_documented = False
    if section_id in (7, 8, 9, 12, 14, 15):
        absence_tokens = [
            "no persistent database", "no relational", "not detected",
            "stateless", "no http", "no api route", "no dedicated test files",
            "no automated test", "no ci/cd", "not identified", "none identified",
            "no container", "host execution", "manual", "absence", "ephemeral"
        ]
        is_absence_documented = any(t in lower_content for t in absence_tokens)

    # Check heading structure: must not contain corrupted numbering like 10-0 or 11-1
    corrupted_heading_match = re.search(r'^#\s+(\d+)[-_](\d+)', clean_content, re.MULTILINE)
    if corrupted_heading_match:
        errors.append(
            f"Section {section_id} contains corrupted heading numbering: '{corrupted_heading_match.group(0)}'."
        )
    # Check for standalone 1 preceding repeated heading
    if re.search(r'^\s*1\s*\n+\s*1\.\s+', clean_content, re.MULTILINE):
        errors.append(
            f"Section {section_id} contains malformed standalone '1' and repeated heading."
        )

    is_valid = len(errors) == 0
    status = "COMPLETE" if is_valid else "FAILED"

    return SectionValidationResult(
        section_id=section_id,
        title=canonical_meta["title"],
        is_valid=is_valid,
        status=status,
        word_count=word_count,
        char_count=char_count,
        errors=errors,
        warnings=warnings,
        has_diagram=has_diagram,
        is_absence_documented=is_absence_documented,
    )


def validate_suite_integrity(
    sections: List[DocSection],
    master_readme: str = "",
    docs_dir: Optional[Path] = None,
    expected_sections: Optional[int] = None,
    active_plan: Optional[List[Dict[str, Any]]] = None,
) -> SuiteIntegrityReport:
    """
    Central Server-Authoritative Completion Gate.
    Verifies that all required sections exist, are in correct sequential order (1..N),
    pass validation, contain no corruption, and assemble into a valid master document.
    """
    errors: List[str] = []
    warnings: List[str] = []
    section_reports: Dict[int, SectionValidationResult] = {}
    missing_ids: List[int] = []
    invalid_ids: List[int] = []

    if active_plan:
        target_count = len(active_plan)
        expected_order = [p["display_number"] for p in active_plan]
    elif expected_sections is not None:
        target_count = expected_sections
        expected_order = list(range(1, target_count + 1))
    else:
        target_count = CANONICAL_SECTIONS_COUNT
        expected_order = list(range(1, CANONICAL_SECTIONS_COUNT + 1))

    # 1. Check sections presence & duplicates
    seen_ids: Set[int] = set()
    duplicate_ids: Set[int] = set()

    for sec in sections:
        if sec.section_number in seen_ids:
            duplicate_ids.add(sec.section_number)
        seen_ids.add(sec.section_number)

    if duplicate_ids:
        errors.append(f"Duplicate section IDs found: {sorted(list(duplicate_ids))}.")

    for required_id in expected_order:
        if required_id not in seen_ids:
            missing_ids.append(required_id)

    if missing_ids:
        errors.append(f"Missing required section IDs: {missing_ids}.")

    # Check for unexpected section IDs (< 1 or > target_count)
    unexpected_ids = [s.section_number for s in sections if s.section_number < 1 or s.section_number > target_count]
    if unexpected_ids:
        errors.append(f"Unexpected non-canonical section IDs found: {unexpected_ids}.")

    # 2. Check each section individually
    sections_by_number = {s.section_number: s for s in sections}
    for disp_num in expected_order:
        sec = sections_by_number.get(disp_num)
        if not sec:
            continue

        canonical_id = getattr(sec, "canonical_id", disp_num) or disp_num
        report = validate_section_content(
            section_id=canonical_id,
            title=sec.title,
            content=sec.content,
            display_number=disp_num,
        )
        section_reports[disp_num] = report

        if not report.is_valid:
            invalid_ids.append(disp_num)
            for err in report.errors:
                errors.append(f"[Section {disp_num}] {err}")

    # 3. Check sequential ordering 1..N
    actual_order = [s.section_number for s in sections]
    if actual_order != expected_order:
        errors.append(f"Sections are not in sequential order 1..{target_count}: actual order is {actual_order}.")

    # 4. Check on-disk files if docs_dir is provided
    if docs_dir and docs_dir.exists():
        if active_plan:
            for p in active_plan:
                canonical_filename = p["filename"]
                canonical_path = docs_dir / canonical_filename
                legacy_path = docs_dir / LEGACY_FILENAMES_BY_ID.get(p.get("canonical_id", p["display_number"]), "")
                if not canonical_path.exists() and not legacy_path.exists():
                    errors.append(f"Section {p['display_number']} file missing on disk: {canonical_filename}")
        else:
            for meta in SECTIONS_META[:target_count]:
                sec_id, _, _, canonical_filename = meta
                canonical_path = docs_dir / canonical_filename
                legacy_path = docs_dir / LEGACY_FILENAMES_BY_ID.get(sec_id, "")
                if not canonical_path.exists() and not legacy_path.exists():
                    errors.append(f"Section {sec_id} file missing on disk: {canonical_filename}")

        # Check for corrupted files on disk
        corrupted_patterns = ["10-0*", "11-1*", "12-1*", "*-0.md", "*-1.md"]
        for pat in corrupted_patterns:
            bad_files = list(docs_dir.glob(pat))
            if bad_files:
                errors.append(f"Corrupted section files detected on disk matching '{pat}': {[f.name for f in bad_files]}")

    # 5. Check Master Document integrity if provided
    master_valid = False
    if master_readme and master_readme.strip():
        master_errors = []
        if active_plan:
            for p in active_plan:
                heading_pat = rf'^#\s+{p["display_number"]}\.\s+{re.escape(p["title"])}'
                if not re.search(heading_pat, master_readme, re.MULTILINE):
                    master_errors.append(f"Master document is missing heading: '# {p['display_number']}. {p['title']}'")
        else:
            for sec_id in expected_order:
                title = CANONICAL_SECTION_BY_ID[sec_id]["title"]
                heading_pat = rf'^#\s+{sec_id}\.\s+{re.escape(title)}'
                if not re.search(heading_pat, master_readme, re.MULTILINE):
                    master_errors.append(f"Master document is missing heading: '# {sec_id}. {title}'")

        if master_errors:
            errors.extend(master_errors)
        else:
            master_valid = True
    elif len(sections) == target_count and not missing_ids and not invalid_ids:
        # Master document might be assembled right after this check
        master_valid = True

    valid_sections_count = len([r for r in section_reports.values() if r.is_valid])
    is_complete = (
        len(errors) == 0
        and len(missing_ids) == 0
        and len(invalid_ids) == 0
        and valid_sections_count == target_count
    )

    status = "COMPLETE" if is_complete else ("PARTIAL" if valid_sections_count > 0 else "FAILED")

    return SuiteIntegrityReport(
        is_complete=is_complete,
        status=status,
        total_sections=target_count,
        valid_sections_count=valid_sections_count,
        missing_section_ids=missing_ids,
        invalid_section_ids=invalid_ids,
        errors=errors,
        warnings=warnings,
        section_reports=section_reports,
        master_document_valid=master_valid,
    )


def assert_suite_complete(sections: List[DocSection], master_readme: str = "") -> None:
    """Raises ValueError if the suite does not pass the strict completion gate."""
    report = validate_suite_integrity(sections, master_readme)
    if not report.is_complete:
        err_msg = "; ".join(report.errors[:5])
        raise ValueError(
            f"Documentation suite failed completion gate ({report.valid_sections_count}/{report.total_sections} valid). Errors: {err_msg}"
        )
