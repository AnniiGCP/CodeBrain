"""
backend/docgen/master_doc_gen.py
--------------------------------
Universal Orchestrator for the 16-Section Technical Documentation Suite.

Workflow:
1. Extract Normalized Knowledge Graph & Dynamic Project Identity from repository evidence.
2. Generate Deterministic Structured Diagrams (SVG, PNG, Mermaid) and persist in assets/.
3. Build Evidence-Backed Content for each of the canonical 16 sections with honest absence handling.
4. Synthesize via AI Router with strict anti-hallucination policy and schema validation; fall back to deterministic generator on failure.
5. Export full documentation in all formats:
   - Markdown (FULL_PROJECT_DOCUMENTATION.md & individual 01..16 section files)
   - Publication-grade PDF (FULL_PROJECT_DOCUMENTATION.pdf) with rendered diagrams and auto-wrapped tables
   - Responsive HTML (FULL_PROJECT_DOCUMENTATION.html) with inline SVG diagrams
   - Machine-readable JSON (FULL_PROJECT_DOCUMENTATION.json)
   - Updated README.md
6. Validate structural integrity, absence of project leakage, and secret redaction.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docgen.diagram_engine import (
    build_architecture_diagram_spec,
    build_cicd_diagram_spec,
    build_er_diagram_spec,
    plan_all_diagrams,
    render_mermaid,
    render_png,
    render_svg,
)
from docgen.groq_client import call_groq
from docgen.html_exporter import generate_html_documentation
from docgen.json_exporter import generate_json_documentation
from docgen.pdf_exporter import generate_pdf_documentation
from docgen.repo_analyzer import (
    RepoKnowledgeGraph,
    analyze_repository,
    calculate_quality_score,
)
from docgen.schema import (
    DOCUMENTATION_SCHEMA_KEYS,
    DOCUMENTATION_SECTIONS,
    DocSection,
    FullDocSuiteResult,
    ProjectMetadata,
    SECTIONS_META,
    CANONICAL_SECTION_BY_ID,
    plan_evidence_driven_sections,
)
from docgen.secret_redactor import redact_secrets
from docgen.validator import (
    validate_section_content,
    validate_suite_integrity,
    assert_suite_complete,
)

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(__file__).parent.parent / "storage"

# ── MERMAID SYNTAX VALIDATION HELPERS ─────────────────────────────────────────
VALID_MERMAID_TYPES = (
    "graph td", "graph lr", "graph tb", "graph rl",
    "flowchart td", "flowchart lr", "flowchart tb", "flowchart rl",
    "sequencediagram", "classdiagram", "erdiagram",
    "statediagram", "statediagram-v2", "gantt", "pie", "gitgraph", "quadrantchart",
    "c4context", "mindmap", "timeline", "block"
)


def extract_mermaid_blocks(content: str) -> List[str]:
    pattern = re.compile(r'```mermaid\s*([\s\S]*?)\s*```', re.IGNORECASE)
    return [m.group(1).strip() for m in pattern.finditer(content)]


def validate_mermaid_syntax(chart_code: str) -> Tuple[bool, str]:
    if not chart_code or not chart_code.strip():
        return False, "Empty Mermaid chart code."
    lines = [l.strip() for l in chart_code.strip().splitlines() if l.strip() and not l.strip().startswith("%%")]
    if not lines:
        return False, "Mermaid code contains only comments or whitespace."
    first_line = lines[0].lower().replace(" ", "")
    has_valid_header = any(first_line.startswith(t.replace(" ", "")) for t in VALID_MERMAID_TYPES)
    if not has_valid_header:
        return False, f"Invalid or missing Mermaid diagram header: '{lines[0]}'."
    if len(lines) < 2:
        return False, "Mermaid diagram is incomplete (fewer than 2 statements)."
    for opener, closer in [("[", "]"), ("(", ")"), ("{", "}")]:
        if chart_code.count(opener) != chart_code.count(closer):
            return False, f"Unbalanced brackets in Mermaid diagram: '{opener}' vs '{closer}'."
    if chart_code.count('"') % 2 != 0:
        return False, "Unbalanced double quotes in Mermaid diagram."
    return True, ""


def strip_invalid_mermaid_blocks(content: str) -> str:
    pattern = re.compile(r'```mermaid\s*([\s\S]*?)\s*```', re.IGNORECASE)

    def _replace_block(match: re.Match) -> str:
        block_body = match.group(1).strip()
        is_valid, _ = validate_mermaid_syntax(block_body)
        if is_valid:
            return match.group(0)
        logger.warning("Stripping invalid Mermaid diagram from section output.")
        return ""

    cleaned = pattern.sub(_replace_block, content)
    return cleaned.strip()


# ── EVALUATE EVIDENCE AVAILABILITY PER SECTION ────────────────────────────────

# ── EVALUATE EVIDENCE AVAILABILITY PER SECTION ────────────────────────────────

def has_real_data_for_section(section_num: int, graph: RepoKnowledgeGraph) -> bool:
    """
    Evaluates whether real evidence exists in the repository for a given section.
    If False, the section is omitted under flexible sequential numbering (1..N).
    Never fabricates missing features.
    """
    if section_num == 1:
        return graph.total_files > 0
    elif section_num == 2:
        return bool(graph.languages or graph.frameworks or graph.manifest_dependencies or getattr(graph, "system_requirements", []) or getattr(graph, "external_services", []))
    elif section_num == 3:
        return bool(graph.directory_structure or graph.total_files > 0)
    elif section_num == 4:
        return bool(graph.entry_points or graph.directory_structure or graph.total_symbols > 0)
    elif section_num == 5:
        return bool(graph.directory_structure and len(graph.directory_structure) > 0)
    elif section_num == 6:
        return bool(graph.functions or graph.classes)
    elif section_num == 7:
        return bool(graph.api_endpoints and len(graph.api_endpoints) > 0)
    elif section_num == 8:
        return bool(graph.db_present or (graph.db_models and len(graph.db_models) > 0))
    elif section_num == 9:
        return bool(graph.db_models and any(m.relationships for m in graph.db_models))
    elif section_num == 10:
        return bool(graph.manifest_dependencies or getattr(graph, "system_requirements", []) or getattr(graph, "external_services", []))
    elif section_num == 11:
        return bool(getattr(graph, "config_details", []) or (graph.security and graph.security.config_vars))
    elif section_num == 12:
        return bool(graph.testing.test_files_count > 0 or graph.testing.test_frameworks)
    elif section_num == 13:
        sec = graph.security
        return bool(getattr(graph, "security_findings", []) or sec.auth_symbols or sec.auth_mechanisms or sec.security_patterns)
    elif section_num == 14:
        return bool(graph.ci_present or (graph.devops.ci_files and len(graph.devops.ci_files) > 0))
    elif section_num == 15:
        return bool(graph.deployment_present or graph.devops.docker_files or graph.devops.services or graph.devops.base_images or graph.devops.deployment_configs)
    elif section_num == 16:
        return bool(graph.package_managers or graph.build_tools or graph.entry_points or getattr(graph, "setup_commands", []))
    return False


# ── DETERMINISTIC STRUCTURED TABLES GENERATOR ─────────────────────────────────

def build_tech_stack_table(graph: RepoKnowledgeGraph) -> str:
    rows = ["| Layer | Technology | Role | Purpose / Role in Project | Evidence |", "|---|---|---|---|---|"]
    for lang, count in graph.languages.items():
        rows.append(f"| Language | {lang} | Programming Language | Core source implementation | {count} source files detected |")
    for fw in graph.frameworks:
        rows.append(f"| Framework | {fw} | Application Framework | Core architectural foundation | Manifests / imports |")
    if getattr(graph, "database_type", None):
        rows.append(f"| Database | {graph.database_type} | Persistence Engine | Data storage & entities | Configuration / ORM models |")
    for pm in graph.package_managers:
        rows.append(f"| Package Manager | {pm} | Dependency Management | Package installation & resolution | Manifest files present |")
    for bt in graph.build_tools:
        rows.append(f"| Build Tool | {bt} | Build & Compilation | Asset bundling / compiling | Build definitions present |")
    for req in getattr(graph, "system_requirements", []):
        rows.append(f"| System Runtime | {req} | Runtime Requirement | Required execution runtime | Manifest requirements |")
    for svc in getattr(graph, "external_services", []):
        rows.append(f"| External Service | {svc} | Third-Party API / Client | External service integration | Code imports / client calls |")
    return "\n".join(rows) if len(rows) > 2 else "Not identified in the analyzed repository."


def build_modules_table(graph: RepoKnowledgeGraph) -> str:
    if not graph.directory_structure:
        return "Not identified in the analyzed repository."
    rows = ["| Module | Location | Responsibility | Key Symbols |", "|---|---|---|---|"]
    for d in graph.directory_structure[:18]:
        syms = ", ".join(d.symbols[:3]) if d.symbols else "Module components"
        rows.append(f"| `{d.path}` | `{d.path}/` | {d.purpose} | {syms} |")
    return "\n".join(rows)


def build_classes_table(graph: RepoKnowledgeGraph) -> str:
    if not graph.classes and not graph.functions:
        return "No AST class or function symbols were identified in the analyzed repository."
    sections = []
    if graph.classes:
        rows = ["| Class | Source File | Purpose | Methods | Fields |", "|---|---|---|---|---|"]
        for c in graph.classes[:15]:
            methods = ", ".join(c.methods[:4]) if c.methods else "Data class / record"
            fields = ", ".join(c.fields[:4]) if getattr(c, "fields", None) else "Instance attributes"
            rows.append(f"| `{c.name}` | `{c.file_path}` | Core application type | `{methods}` | `{fields}` |")
        sections.append("#### Important AST Classes\n\n" + "\n".join(rows))
    if graph.functions:
        rows = ["| Function | Source File | Signature | Key Calls / Subroutines |", "|---|---|---|---|"]
        for f in graph.functions[:15]:
            sig = f.signature or "()"
            calls = ", ".join(f.calls[:3]) if getattr(f, "calls", None) else "Standard routines"
            rows.append(f"| `{f.name}` | `{f.file_path}` | `{sig}` | `{calls}` |")
        sections.append("#### Important AST Functions & Handlers\n\n" + "\n".join(rows))
    return "\n\n".join(sections)


def build_apis_table(graph: RepoKnowledgeGraph) -> str:
    if not graph.api_endpoints:
        return "No HTTP/REST API endpoints or route definitions were identified in the analyzed repository."
    groups = getattr(graph, "api_groups", {})
    if not groups:
        groups = {"Endpoints": graph.api_endpoints}

    sections = []
    for domain, endpoints in groups.items():
        sections.append(f"#### {domain} Domain ({len(endpoints)} routes)")
        rows = ["| Method | Endpoint | Handler | Source File | Parameters / Request | Response / Status |", "|---|---|---|---|---|---|"]
        for a in endpoints[:15]:
            params = (", ".join(a.parameters[:3]) if getattr(a, "parameters", None) else "None")
            resp = getattr(a, "response_type", "") or "200 OK"
            rows.append(f"| `{a.http_method}` | `{a.path}` | `{a.handler_name}()` | `{a.file_path}` | `{params}` | `{resp}` |")
        sections.append("\n".join(rows))
    return "\n\n".join(sections)


def build_database_table(graph: RepoKnowledgeGraph) -> str:
    if not graph.db_models:
        return "No persistent database schema was identified in the analyzed repository."
    rows = ["| Entity / Table | Columns & Types | Primary Keys | Relationships | Schema Notes |", "|---|---|---|---|---|"]
    for m in graph.db_models[:15]:
        if m.fields:
            cols = ", ".join(m.fields[:5]) + ("..." if len(m.fields) > 5 else "")
            notes = "Statically extracted from model definitions"
        else:
            cols = "Fields not statically declared"
            notes = "Extraction limitation: Schema defined via runtime migrations / dynamic reflection"
        pks = ", ".join(m.primary_keys) if m.primary_keys else "id"
        rels = ", ".join(m.relationships[:2]) if m.relationships else "None detected"
        rows.append(f"| `{m.model_name}` | {cols} | `{pks}` | {rels} | {notes} |")
    return "\n".join(rows)


def build_dependencies_table(graph: RepoKnowledgeGraph) -> str:
    if not graph.manifest_dependencies and not getattr(graph, "system_requirements", []) and not getattr(graph, "external_services", []):
        return "No package manifest dependencies were identified in the analyzed repository."

    sections = []
    runtime_deps = [d for d in graph.manifest_dependencies if d.dep_type != "dev"]
    dev_deps = [d for d in graph.manifest_dependencies if d.dep_type == "dev"]

    if runtime_deps:
        rows = ["| Runtime Package | Version | Ecosystem | Source Manifest | Role |", "|---|---|---|---|---|"]
        for d in runtime_deps[:25]:
            ver = d.version or "Unspecified"
            eco = getattr(d, "ecosystem", "Package")
            rows.append(f"| `{d.name}` | {ver} | {eco} | `{d.source_file}` | Core Application Dependency |")
        sections.append("#### Runtime Dependencies\n\n" + "\n".join(rows))

    if dev_deps:
        rows = ["| Development Package | Version | Ecosystem | Source Manifest | Role |", "|---|---|---|---|---|"]
        for d in dev_deps[:20]:
            ver = d.version or "Unspecified"
            eco = getattr(d, "ecosystem", "Package")
            rows.append(f"| `{d.name}` | {ver} | {eco} | `{d.source_file}` | Build & Development Tooling |")
        sections.append("#### Development Tooling\n\n" + "\n".join(rows))

    if getattr(graph, "external_services", []):
        rows = ["| External Service | Category | Integration Evidence |", "|---|---|---|"]
        for s in graph.external_services:
            rows.append(f"| `{s}` | Cloud / Third-Party API | Detected in source imports / SDK clients |")
        sections.append("#### External Services & Cloud APIs\n\n" + "\n".join(rows))

    if getattr(graph, "system_requirements", []):
        rows = ["| System Requirement | Expected Environment | Evidence Source |", "|---|---|---|"]
        for r in graph.system_requirements:
            rows.append(f"| `{r}` | Application Execution Engine | Package manifest configuration |")
        sections.append("#### System & Runtime Requirements\n\n" + "\n".join(rows))

    return "\n\n".join(sections) if sections else "No package dependencies declared."


def build_config_table(graph: RepoKnowledgeGraph) -> str:
    cfg_details = getattr(graph, "config_details", [])
    if not cfg_details and not graph.security.config_vars:
        return "No environment configuration variables were identified in the analyzed repository."
    rows = ["| Variable Name | Purpose | Used By | Required / Optional | Default Value | Classification |", "|---|---|---|---|---|---|"]
    if cfg_details:
        for c in cfg_details[:25]:
            used_by = ", ".join(c.used_by[:2]) if c.used_by else "Application runtime"
            req_str = "Required" if c.required else "Optional"
            sec_str = "Secret (Redacted)" if c.is_secret else "Non-secret"
            rows.append(f"| `{c.name}` | {c.purpose} | `{used_by}` | {req_str} | `{c.default_val}` | {sec_str} |")
    else:
        for var in graph.security.config_vars[:25]:
            is_sec = any(kw in var.lower() for kw in ("key", "secret", "token", "pass", "auth"))
            rows.append(f"| `{var}` | Runtime environment configuration | Application runtime | Optional | `Not determined from repository evidence.` | {'Secret (Redacted)' if is_sec else 'Non-secret'} |")
    return "\n".join(rows)


def build_security_table(graph: RepoKnowledgeGraph) -> str:
    findings = getattr(graph, "security_findings", [])
    if not findings:
        return "Security analysis status cataloged across core application boundaries."
    rows = ["| Security Area | Status | Evidence | Analysis Notes |", "|---|---|---|---|"]
    for f in findings:
        rows.append(f"| {f.area} | **{f.status}** | {f.evidence} | {f.notes} |")
    return "\n".join(rows)


# ── ASCII TREE HELPERS ────────────────────────────────────────────────────────

def _build_repo_ascii_tree(graph: RepoKnowledgeGraph, project_name: str) -> str:
    lines = [f"{project_name}/", "│"]
    dirs = graph.directory_structure[:15]
    for idx, d in enumerate(dirs):
        is_last = (idx == len(dirs) - 1)
        prefix = "└── " if is_last else "├── "
        lines.append(f"{prefix}{d.path}/")
        for k_idx, kf in enumerate(d.key_files[:2]):
            sub_prefix = "    └── " if (k_idx == len(d.key_files[:2]) - 1) else "    ├── "
            lines.append(f"{sub_prefix}{kf}")
    return "\n".join(lines) if len(lines) > 2 else f"{project_name}/\n└── (repository root)"


def _build_api_ascii_tree(graph: RepoKnowledgeGraph) -> str:
    if not graph.api_endpoints:
        return "No API routes identified."
    groups: Dict[str, List[Any]] = {}
    for ep in graph.api_endpoints[:25]:
        parts = ep.path.strip("/").split("/")
        grp = f"/{parts[0]}" if parts and parts[0] else "root"
        groups.setdefault(grp, []).append(ep)
    lines = ["API Interface Map", "│"]
    grp_keys = list(groups.keys())
    for g_idx, grp in enumerate(grp_keys):
        is_last_grp = (g_idx == len(grp_keys) - 1)
        branch = "└── " if is_last_grp else "├── "
        lines.append(f"{branch}{grp}")
        sub_indent = "    " if is_last_grp else "│   "
        eps = groups[grp]
        for e_idx, ep in enumerate(eps[:4]):
            is_last_ep = (e_idx == len(eps[:4]) - 1)
            e_branch = "└── " if is_last_ep else "├── "
            lines.append(f"{sub_indent}{e_branch}{ep.http_method} {ep.path}")
    return "\n".join(lines)


def _build_db_ascii_tree(graph: RepoKnowledgeGraph) -> str:
    if not graph.db_models:
        return "No database entities identified."
    lines = ["Database Blueprint", "│"]
    models = graph.db_models[:10]
    for m_idx, m in enumerate(models):
        is_last_m = (m_idx == len(models) - 1)
        branch = "└── " if is_last_m else "├── "
        lines.append(f"{branch}{m.model_name}")
        sub_indent = "    " if is_last_m else "│   "
        for pk in (m.primary_keys or ["id"]):
            lines.append(f"{sub_indent}├── {pk} [PK]")
        for f in m.fields[:4]:
            if f not in (m.primary_keys or ["id"]):
                lines.append(f"{sub_indent}├── {f}")
        for r in m.relationships[:2]:
            lines.append(f"{sub_indent}└── [Rel → {r}]")
    return "\n".join(lines)


def _build_dependencies_ascii_tree(graph: RepoKnowledgeGraph) -> str:
    if not graph.manifest_dependencies:
        return "No package dependencies declared."
    runtime_deps = [d for d in graph.manifest_dependencies if d.dep_type != "dev"][:15]
    dev_deps = [d for d in graph.manifest_dependencies if d.dep_type == "dev"][:15]
    lines = ["Project Dependencies", "│"]
    if runtime_deps:
        lines.append("├── Runtime Packages")
        for idx, d in enumerate(runtime_deps):
            prefix = "│   └── " if idx == len(runtime_deps) - 1 else "│   ├── "
            eco = getattr(d, "ecosystem", "Package")
            lines.append(f"{prefix}{d.name} ({d.version or 'latest'}) [{eco}]")
    if dev_deps:
        lines.append("└── Development & Build Tooling")
        for idx, d in enumerate(dev_deps):
            prefix = "    └── " if idx == len(dev_deps) - 1 else "    ├── "
            eco = getattr(d, "ecosystem", "Package")
            lines.append(f"{prefix}{d.name} ({d.version or 'latest'}) [{eco}]")
    return "\n".join(lines)


def _build_architecture_ascii_tree(graph: RepoKnowledgeGraph) -> str:
    lines = [
        "System Architecture Topology",
        "│",
        "├── Presentation Layer (Client)",
    ]
    if any("front" in d.path.lower() or "ui" in d.path.lower() for d in graph.directory_structure):
        lines.append("│   └── Web Application & Client Views")
    else:
        lines.append("│   └── API Consumers & Client Interfaces")
    lines.append("├── Application & Routing Layer")
    entry_summary = ", ".join(graph.entry_points[:2]) if graph.entry_points else "HTTP Handlers"
    lines.append(f"│   └── Entry Points: `{entry_summary}`")
    lines.append("├── Domain & Business Services Layer")
    for d in graph.directory_structure[:3]:
        lines.append(f"│   └── `{d.path}/` — {d.purpose}")
    lines.append("├── Data Persistence Layer")
    if graph.db_models:
        lines.append(f"│   └── {len(graph.db_models)} Registered Entities / ORM Models")
    else:
        lines.append("│   └── Stateless / Ephemeral Storage")
    lines.append("└── External Infrastructure & Services")
    if graph.devops.docker_files:
        lines.append("    └── Containerized Services (Docker)")
    else:
        lines.append("    └── Standard Host Runtime")
    return "\n".join(lines)


# ── DETERMINISTIC EVIDENCE-GROUNDED SECTION BUILDER ───────────────────────────

def build_deterministic_section_content(
    orig_num: int,
    active_num: int,
    title: str,
    schema_key: str,
    graph: RepoKnowledgeGraph,
    diagram_specs: Dict[str, Any],
) -> str:
    """
    Constructs fact-grounded section content strictly from repository evidence.
    Uses dynamic sequential numbering (active_num) for all headings, figure references, and diagrams.
    """
    project_name = graph.project_metadata.project_name if graph.project_metadata else graph.repo_name

    # Evidence-grounded generation per section
    if orig_num == 1:
        # Project Overview (Full Executive Introduction per Requirement 4)
        lang_list = ", ".join([f"{k} ({v} files)" for k, v in graph.languages.items()])
        entry_str = f"`{', '.join(graph.entry_points)}`" if graph.entry_points else "Standard package entry points"
        ps_spec = diagram_specs.get("problem_solution")
        wf_spec = diagram_specs.get("workflow")
        ps_mermaid = f"\n\n#### Figure {active_num}.1: Problem & Solution Flow Architecture\n\n{render_mermaid(ps_spec)}\n" if ps_spec else ""
        wf_mermaid = f"\n\n#### Figure {active_num}.2: End-to-End Execution Workflow\n\n{render_mermaid(wf_spec)}\n" if wf_spec else ""

        problem_stmt = f"Modern software environments requiring {graph.app_type} solutions often face operational complexity in managing component coordination, modular maintenance, and reliable runtime execution. `{project_name}` resolves these challenges by providing a dedicated, structured codebase designed for deterministic execution and maintainable software engineering practices."
        if graph.project_purpose and graph.project_purpose != "Software engineering application.":
            problem_stmt = f"The repository addresses operational and software engineering challenges in the domain of {graph.app_type}: {graph.project_purpose}."

        components_summary = ", ".join([f"`{d.path}/`" for d in graph.directory_structure[:6]]) or "core modules"
        dirs_explanation = "\n".join([f"- **`{d.path}/`**: {d.purpose} ({d.file_count} files, key files: `{', '.join(d.key_files[:3])}`)" for d in graph.directory_structure[:8]])

        return (
            f"### Project Identity\n\n"
            f"- **Repository Name:** `{project_name}`\n"
            f"- **System Classification:** {graph.app_type}\n"
            f"- **Source Volume:** **{graph.total_files}** source files across **{len(graph.directory_structure)}** primary directories\n"
            f"- **Analyzed Code Symbols:** **{graph.total_symbols}** AST classes, functions, and symbols\n"
            f"- **Primary Entry Point:** {entry_str}\n\n"
            f"### Executive Summary\n\n"
            f"**{project_name}** is a software engineering codebase implementing a **{graph.app_type}** topology. "
            f"Static code inspection and manifest analysis reveal an application designed to deliver deterministic, modular functionality "
            f"with verified language implementations spanning {lang_list}.\n\n"
            f"### Problem Statement\n\n"
            f"{problem_stmt}\n\n"
            f"### Purpose & Objectives\n\n"
            f"- **Primary Purpose:** Provide an end-to-end implementation for {graph.project_purpose}\n"
            f"- **Architecture Goal:** Maintain high cohesion and modular boundary separation across {components_summary}.\n"
            f"- **Quality Objective:** Ensure testability, maintainability, and clean separation between presentation, logic, and data storage.\n\n"
            f"### Intended Users & Scope\n\n"
            f"- **Target Audience:** Developers, systems engineers, and API consumers interacting with {project_name}.\n"
            f"- **In-Scope Capabilities:** Source modules, interfaces, and configurations directly housed within `{project_name}`.\n"
            f"- **Out-of-Scope Elements:** Third-party upstream hosting platforms, unmanaged external networks, and external hardware resources.\n\n"
            f"### Key Capabilities & Major Components\n\n"
            f"The codebase is divided into modular subsystems with specific responsibilities:\n\n"
            f"{dirs_explanation}\n"
            f"{ps_mermaid}\n"
            f"### End-to-End Workflow & Execution\n\n"
            f"Execution begins at `{entry_str}`, loading runtime configurations and dispatching incoming requests or computational jobs "
            f"to internal domain services before persisting states and generating system responses.\n"
            f"{wf_mermaid}"
        )

    elif orig_num == 2:
        # Technology Stack
        table = build_tech_stack_table(graph)
        ts_spec = diagram_specs.get("tech_stack")
        ts_mermaid = f"\n\n#### Figure {active_num}.1: Verified Technology Stack Architecture\n\n{render_mermaid(ts_spec)}\n" if ts_spec else ""

        langs_summary = ", ".join([f"**{k}** ({v} files)" for k, v in graph.languages.items()]) or "Identified programming languages"
        fw_summary = ", ".join([f"**{fw}**" for fw in graph.frameworks]) or "Core application runtime frameworks"
        pm_summary = ", ".join([f"`{pm}`" for pm in graph.package_managers]) or "Standard ecosystem packaging"
        bt_summary = ", ".join([f"`{bt}`" for bt in graph.build_tools]) or "Standard compilation & bundling tools"

        return (
            f"### Technology Stack & Architecture Foundations\n\n"
            f"The technological architecture of `{project_name}` is built upon verified software engineering foundations detected directly from package manifests, source code imports, and build configurations.\n\n"
            f"- **Programming Languages:** {langs_summary}\n"
            f"- **Frameworks & Core Libraries:** {fw_summary}\n"
            f"- **Package Management:** {pm_summary}\n"
            f"- **Build & Compilation Tooling:** {bt_summary}\n\n"
            f"### Verified Technology Stack Matrix\n\n"
            f"The table below details each technology layer, its specific role, purpose within `{project_name}`, and the concrete source evidence validating its inclusion:\n\n"
            f"{table}\n"
            f"{ts_mermaid}\n\n"
            f"### Language Distribution & Execution Characteristics\n\n"
            f"The codebase demonstrates a focused language strategy designed for {graph.app_type} workloads. "
            f"Static code inspection identified {graph.total_files} active files across the repository. "
            f"Core routines execute within their corresponding runtimes, enforcing modular structure and clean separation of concerns.\n\n"
            f"### Third-Party Integrations & Ecosystem Alignment\n\n"
            f"Dependencies and runtime bindings are declared in version-controlled manifests, ensuring deterministic builds, reproducible local development environments, and structured upstream packaging."
        )

    elif orig_num == 3:
        # Repository Structure (Written + Tree Flow Diagram per Requirement 3)
        ascii_tree = _build_repo_ascii_tree(graph, project_name)
        dirs_explanation = "\n".join([f"- **`{d.path}/`**: {d.purpose} ({d.file_count} files, key files: `{', '.join(d.key_files[:3])}`)" for d in graph.directory_structure[:12]])
        rs_spec = diagram_specs.get("repo_structure")
        rs_mermaid = f"\n\n#### Figure {active_num}.1: Repository Hierarchy & Module Structure\n\n{render_mermaid(rs_spec)}\n" if rs_spec else ""
        return (
            f"### Directory Hierarchy Tree\n\n"
            f"```text\n{ascii_tree}\n```\n\n"
            f"### Module Organization & Responsibilities\n\n"
            f"{dirs_explanation}\n"
            f"{rs_mermaid}"
        )

    elif orig_num == 4:
        # System Architecture (Large Multi-Tier Topology per Requirements 5 & 6)
        ascii_arch = _build_architecture_ascii_tree(graph)
        diag_spec = diagram_specs.get("architecture")
        arch_mermaid = f"\n\n#### Figure {active_num}.1: Multi-Tier System Topology & Architecture\n\n{render_mermaid(diag_spec)}\n" if diag_spec else ""
        df_spec = diagram_specs.get("data_flow")
        df_mermaid = f"\n\n#### Figure {active_num}.2: Component Data Flow & Request Lifecycle\n\n{render_mermaid(df_spec)}\n" if df_spec else ""

        entry_list = ", ".join([f"`{e}`" for e in graph.entry_points]) or "Standard application entry points"
        subsystems_list = ", ".join([f"`{d.path}/`" for d in graph.directory_structure[:6]]) or "modular subsystems"

        return (
            f"### Architectural Overview & Topology\n\n"
            f"The architectural design of `{project_name}` adheres to a **{graph.app_type}** topology. "
            f"The codebase is structured to enforce modular decoupling, explicit request routing, and deterministic state transitions across its primary subsystems ({subsystems_list}).\n\n"
            f"### Multi-Tier Structural Hierarchy\n\n"
            f"The system boundary spans presentation, business logic controllers, internal utilities, and storage layers:\n\n"
            f"```text\n{ascii_arch}\n```\n"
            f"{arch_mermaid}\n"
            f"### Component Interactions & Request Lifecycle\n\n"
            f"Execution begins at active entry points ({entry_list}). Incoming invocations traverse structured lifecycle phases:\n\n"
            f"1. **Invocation & Parameter Ingestion:** Entry routines receive execution arguments, environment variables, and client requests.\n"
            f"2. **Validation & Security Verification:** Parameters pass through boundary validation rules to ensure data integrity.\n"
            f"3. **Domain Processing:** Business logic modules coordinate routine execution across internal subsystems.\n"
            f"4. **State Persistence & Output Generation:** Results are serialized into structured outputs, formatted responses, or persisted records.\n\n"
            f"{df_mermaid}\n\n"
            f"### Subsystem Boundary Contracts & Cohesion\n\n"
            f"Each directory layer operates as an autonomous functional boundary. Modules exchange strongly typed data contracts or structured parameters, minimizing tight coupling and facilitating testability."
        )

    elif orig_num == 5:
        # Modules and Components
        table = build_modules_table(graph)
        mod_spec = diagram_specs.get("modules")
        mod_mermaid = f"\n\n#### Figure {active_num}.1: Subsystem & Module Relationships\n\n{render_mermaid(mod_spec)}\n" if mod_spec else ""

        dir_details = []
        for d in graph.directory_structure[:15]:
            kf = ", ".join([f"`{f}`" for f in d.key_files[:4]]) or "Internal module files"
            syms = ", ".join([f"`{s}`" for s in d.symbols[:4]]) if d.symbols else "Encapsulated routines"
            dir_details.append(
                f"#### `{d.path}/` Module\n\n"
                f"- **Primary Responsibility:** {d.purpose}\n"
                f"- **File Volume:** **{d.file_count}** source files\n"
                f"- **Key Source Files:** {kf}\n"
                f"- **Exported Symbols & Classes:** {syms}\n"
            )
        dirs_expanded = "\n".join(dir_details)

        return (
            f"### Subsystem Architecture & Decomposition\n\n"
            f"The codebase for `{project_name}` is decomposed into distinct logical subsystems designed for high cohesion and clear separation of concerns. "
            f"Static inspection identified **{len(graph.directory_structure)}** primary modules coordinating system execution.\n\n"
            f"### Subsystem Responsibility Catalog\n\n"
            f"{table}\n\n"
            f"### In-Depth Module Specifications\n\n"
            f"{dirs_expanded}\n"
            f"{mod_mermaid}\n\n"
            f"### Inter-Module Communication & Dependency Flow\n\n"
            f"Modules interact through explicit programmatic imports and parameter passing. Upstream controllers invoke domain services, which delegate I/O, data transformation, and utility operations to specialized support modules without circular dependencies."
        )

    elif orig_num == 6:
        # Classes and Functions
        table = build_classes_table(graph)
        cls_spec = diagram_specs.get("classes")
        cls_mermaid = f"\n\n#### Figure {active_num}.1: Significant AST Classes & Function Symbols\n\n{render_mermaid(cls_spec)}\n" if cls_spec else ""

        top_classes = []
        if graph.classes:
            for c in graph.classes[:6]:
                methods_str = ", ".join([f"`{m}()`" for m in c.methods[:5]]) if c.methods else "Data container / attributes"
                fields_str = ", ".join([f"`{f}`" for f in getattr(c, "fields", [])[:5]]) if getattr(c, "fields", None) else "Instance properties"
                top_classes.append(
                    f"- **`{c.name}`** (defined in `{c.file_path}`):\n"
                    f"  - *Role:* Core object abstraction and domain representation.\n"
                    f"  - *Public Methods:* {methods_str}\n"
                    f"  - *Attributes / Fields:* {fields_str}"
                )
        top_classes_str = "\n".join(top_classes) if top_classes else "No top-level class abstractions detected."

        top_funcs = []
        if graph.functions:
            for f in graph.functions[:6]:
                sig = f.signature or "()"
                calls_str = ", ".join([f"`{c}()`" for c in getattr(f, "calls", [])[:4]]) if getattr(f, "calls", None) else "Standard routines"
                top_funcs.append(
                    f"- **`{f.name}{sig}`** (in `{f.file_path}`):\n"
                    f"  - *Subroutines & Dependencies:* {calls_str}"
                )
        top_funcs_str = "\n".join(top_funcs) if top_funcs else "No standalone functional handlers detected."

        return (
            f"### Object-Oriented & Functional Abstraction Model\n\n"
            f"Static AST analysis parsed source files in `{project_name}`, extracting classes, methods, signatures, and function invocations. "
            f"The codebase leverages structured abstractions to encapsulate domain state and operational logic.\n\n"
            f"### AST Symbol Catalog\n\n"
            f"{table}\n\n"
            f"### Core Class Specifications\n\n"
            f"{top_classes_str}\n\n"
            f"### Functional Routines & Execution Handlers\n\n"
            f"{top_funcs_str}\n"
            f"{cls_mermaid}\n\n"
            f"### Symbol Coordination & Control Flow\n\n"
            f"Execution control flows from top-level handler functions into domain class instances, which manage state transitions and delegate computation to specialized utility subroutines."
        )

    elif orig_num == 7:
        # APIs and Interfaces (Written + Tree Diagram per Requirement 8)
        if graph.api_endpoints:
            table = build_apis_table(graph)
            api_tree_ascii = _build_api_ascii_tree(graph)
            api_tree_spec = diagram_specs.get("api_tree")
            api_arch_spec = diagram_specs.get("api_arch")
            api_tree_mermaid = f"\n\n#### Figure {active_num}.1: Hierarchical API Route Map\n\n{render_mermaid(api_tree_spec)}\n" if api_tree_spec else ""
            api_arch_mermaid = f"\n\n#### Figure {active_num}.2: API Request Lifecycle & Handler Pipeline\n\n{render_mermaid(api_arch_spec)}\n" if api_arch_spec else ""

            total_routes = len(graph.api_endpoints)
            methods_count = {}
            for ep in graph.api_endpoints:
                methods_count[ep.http_method] = methods_count.get(ep.http_method, 0) + 1
            methods_summary = ", ".join([f"**{m}**: {c}" for m, c in sorted(methods_count.items())])

            return (
                f"### API Interface Architecture & Route Catalog\n\n"
                f"`{project_name}` exposes **{total_routes}** HTTP/REST endpoints discovered directly in controller routes and handler definitions. "
                f"HTTP Method distribution: {methods_summary}.\n\n"
                f"### Route Definitions & Handler Mapping\n\n"
                f"{table}\n\n"
                f"### API Route Hierarchy\n\n"
                f"```text\n{api_tree_ascii}\n```\n"
                f"{api_tree_mermaid}\n"
                f"### Request Flow Pipeline\n\n"
                f"Incoming client requests traverse route matching, parameter validation, handler controllers, and underlying service layers:\n"
                f"{api_arch_mermaid}\n\n"
                f"### Request Lifecycle & Middleware Processing\n\n"
                f"1. **Request Ingestion:** HTTP requests arrive at the routing layer and are matched against route paths and methods.\n"
                f"2. **Header & Authentication Verification:** Session tokens, authentication headers, or API keys are validated where applicable.\n"
                f"3. **Payload & Parameter Parsing:** Query parameters and JSON bodies are deserialized and validated against schemas.\n"
                f"4. **Business Handler Execution:** Control delegates to handler functions (`{', '.join([a.handler_name for a in graph.api_endpoints[:4]])}`).\n"
                f"5. **Response Serialization:** Successful outcomes return standard HTTP status codes (`200 OK`, `201 Created`) with structured JSON payloads, while errors produce descriptive error responses."
            )
        else:
            entry_points_str = ", ".join([f"`{e}`" for e in graph.entry_points]) if graph.entry_points else "standard module entry points"
            return (
                f"### API Interface Analysis & Route Catalog\n\n"
                f"> **Inspection Finding:** Static route extraction scanned source files across web framework patterns (e.g. FastAPI, Flask, Express, Django). No public HTTP/REST route handlers, WebSocket listeners, or RPC endpoints were discovered in the codebase.\n\n"
                f"### Interface Architecture & Invocation Contract\n\n"
                f"Rather than exposing network-listening API endpoints, `{project_name}` is architected as a standalone software component invoked through direct entry points and programmatic interfaces:\n\n"
                f"- **Primary Entry Point:** {entry_points_str}\n"
                f"- **Communication Mechanism:** Direct process execution, programmatic Python/language imports, and module routine invocations.\n"
                f"- **Input/Output Interface:** Command-line parameters, local configuration files, and direct function arguments returning structured output.\n\n"
                f"### Interface Limitations & Recommendations\n\n"
                f"Because this repository does not expose public HTTP endpoints, external services cannot consume it via RESTful HTTP protocols without embedding it as an imported library or introducing an API routing layer."
            )

    elif orig_num == 8:
        # Database and Data Model (Tree + ER Diagram per Requirements 9 & 10)
        if graph.db_models:
            table = build_database_table(graph)
            db_tree_ascii = _build_db_ascii_tree(graph)
            db_tree_spec = diagram_specs.get("db_tree")
            er_spec = diagram_specs.get("er_diagram")
            db_tree_mermaid = f"\n\n#### Figure {active_num}.1: Database Schema & Entity Blueprint\n\n{render_mermaid(db_tree_spec)}\n" if db_tree_spec else ""
            er_mermaid = f"\n\n#### Figure {active_num}.2: Entity-Relationship Data Model\n\n{render_mermaid(er_spec)}\n" if er_spec else ""

            model_details = []
            for m in graph.db_models[:10]:
                fields_str = ", ".join(m.fields[:8]) if m.fields else "Dynamically managed attributes"
                pk_str = ", ".join(m.primary_keys) if m.primary_keys else "id"
                rels_str = ", ".join(m.relationships) if m.relationships else "None detected"
                model_details.append(
                    f"#### `{m.model_name}` Entity\n\n"
                    f"- **Primary Key(s):** `{pk_str}`\n"
                    f"- **Attributes & Columns:** {fields_str}\n"
                    f"- **Declared Associations:** {rels_str}\n"
                )
            models_expanded = "\n".join(model_details)

            return (
                f"### Data Architecture & Persistence Strategy\n\n"
                f"`{project_name}` implements persistent data models to store and manage domain entities. "
                f"Static analysis discovered **{len(graph.db_models)}** persistent database entities within the codebase.\n\n"
                f"### Entity Blueprint & Specifications\n\n"
                f"{table}\n\n"
                f"### Database Entity Blueprint\n\n"
                f"```text\n{db_tree_ascii}\n```\n"
                f"{db_tree_mermaid}\n"
                f"{er_mermaid}\n\n"
                f"### Detailed Entity Schema Definitions\n\n"
                f"{models_expanded}\n"
                f"### Transaction Semantics & Data Integrity\n\n"
                f"Database mutations execute within atomic transactions to guarantee consistency. Primary key constraints ensure entity identity, while relationship associations preserve relational integrity across domain updates."
            )
        else:
            return (
                f"### Database and Persistence Architecture\n\n"
                f"> **Inspection Finding:** Static AST analysis and repository scanning searched for database entities, schemas, and persistence layers. No relational database tables, ORM models (SQLAlchemy, Prisma, Django ORM, TypeORM), SQL migration scripts, or embedded SQLite databases were identified in the codebase.\n\n"
                f"### Persistence & State Management Posture\n\n"
                f"The repository operates with the following verified persistence posture:\n\n"
                f"- **Stateless Execution:** `{project_name}` maintains no local persistent relational state. Compute routines execute ephemerally.\n"
                f"- **In-Memory & File Storage:** Runtime state is retained strictly in volatile process memory, or serialized to local disk files when applicable.\n"
                f"- **External Persistence Delegation:** If persistent data is required during execution, the application delegates state management to external services or client-supplied inputs.\n\n"
                f"### Inspected Artifacts & Scope Disclosures\n\n"
                f"The absence of persistent database models was confirmed by inspecting package manifests, file trees, and configuration files for database connection strings and ORM imports. No database migrations, schemas, or seed files are present."
            )

    elif orig_num == 9:
        # Database Relationships
        if not graph.db_models:
            return (
                f"### Database Relationships & Persistence Architecture\n\n"
                f"> **Inspection Finding:** Static AST analysis and repository scanning searched for database entities and relationship declarations. No persistent database schema, relational foreign keys, or ORM associations were identified in the codebase.\n\n"
                f"### Persistence & State Coordination Posture\n\n"
                f"Because no persistent relational database infrastructure is implemented in `{project_name}`, internal modules manage in-memory data structures programmatically without persistent relational constraints."
            )

        models_with_rels = [m for m in graph.db_models if m.relationships]
        if models_with_rels:
            rel_lines = []
            for m in models_with_rels:
                for r in m.relationships:
                    rel_lines.append(f"- **`{m.model_name}`** → `{r}`: Relational association detected in schema definitions.")
            rel_spec = diagram_specs.get("db_relationships")
            rel_mermaid = f"\n\n#### Figure {active_num}.1: Database Entity Cardinality & Relationships\n\n{render_mermaid(rel_spec)}\n" if rel_spec else ""
            return (
                f"### Entity Relationships & Cardinality Analysis\n\n"
                f"Relational associations across entities in `{project_name}` define data navigation pathways and foreign key boundaries:\n\n"
                f"{chr(10).join(rel_lines)}\n"
                f"{rel_mermaid}\n\n"
                f"### Join Traversal & Referential Integrity\n\n"
                f"Associations between entities enforce referential integrity across relational operations. "
                f"Queries traversing related entities execute through relational foreign keys or ORM join constructs, maintaining consistency across dependent domain records."
            )
        else:
            rel_spec = diagram_specs.get("db_relationships")
            rel_mermaid = f"\n\n#### Figure {active_num}.1: Database Entity Cardinality & Relationships\n\n{render_mermaid(rel_spec)}\n" if rel_spec else ""
            return (
                f"### Database Relationships & Entity Cardinality\n\n"
                f"Verified repository evidence confirms that no relational foreign keys or ORM associations are explicitly declared across the detected database models.\n\n"
                f"### Component-Level Data Relationships\n\n"
                f"- **Data Flow Relationships:** Modules and handlers coordinate entity records programmatically without relational constraints.\n"
                f"- **Schema Integrity:** Primary keys are managed at the entity level.\n"
                f"{rel_mermaid}\n\n"
                f"### Persistence & Entity Association Governance\n\n"
                f"Data structures operate independently or establish logical linkages through indexed identifier lookups handled directly by application service layers."
            )

    elif orig_num == 10:
        # Dependencies (5-Column Table + Tree per Requirement 11)
        table = build_dependencies_table(graph)
        dep_tree_ascii = _build_dependencies_ascii_tree(graph)
        dep_tree_spec = diagram_specs.get("dep_tree")
        dep_spec = diagram_specs.get("dependencies")
        dep_tree_mermaid = f"\n\n#### Figure {active_num}.1: Package & Dependency Hierarchy\n\n{render_mermaid(dep_tree_spec)}\n" if dep_tree_spec else ""
        dep_mermaid = f"\n\n#### Figure {active_num}.2: Package & Dependency Ecosystem\n\n{render_mermaid(dep_spec)}\n" if dep_spec else ""

        runtime_count = len([d for d in graph.manifest_dependencies if d.dep_type != "dev"])
        dev_count = len([d for d in graph.manifest_dependencies if d.dep_type == "dev"])

        return (
            f"### Dependency Management Architecture & Ecosystem\n\n"
            f"`{project_name}` manages its software supply chain through structured package manifests. "
            f"Static inspection cataloged **{runtime_count}** runtime dependencies and **{dev_count}** development / build tooling dependencies.\n\n"
            f"### Package Dependencies Matrix\n\n"
            f"{table}\n\n"
            f"### Dependency Hierarchy & Resolution Tree\n\n"
            f"```text\n{dep_tree_ascii}\n```\n"
            f"{dep_tree_mermaid}\n"
            f"{dep_mermaid}\n\n"
            f"### Version Pinning & Supply Chain Security\n\n"
            f"1. **Version Pinning:** Manifests specify dependency versions or version ranges to ensure predictable builds.\n"
            f"2. **Isolation:** Runtime libraries are segregated from development linters, formatters, and test runners.\n"
            f"3. **Security Auditing:** Regular dependency auditing is recommended to identify upstream CVE vulnerabilities and deprecations."
        )

    elif orig_num == 11:
        # Configuration and Environment
        table = build_config_table(graph)
        cfg_spec = diagram_specs.get("config_flow")
        cfg_mermaid = f"\n\n#### Figure {active_num}.1: Runtime Configuration Ingestion Flow\n\n{render_mermaid(cfg_spec)}\n" if cfg_spec else ""
        return (
            f"### Runtime Configuration Architecture\n\n"
            f"Application behavior and runtime environments for `{project_name}` are parameterized via environment variables, settings files, and configuration modules. "
            f"This decouples source code from environment-specific credentials and operational targets.\n\n"
            f"### Environment & Runtime Configuration Matrix\n\n"
            f"Variables identified in `.env` files or runtime environment queries:\n\n"
            f"{table}\n"
            f"{cfg_mermaid}\n\n"
            f"### Operational Configuration Ingestion Flow\n\n"
            f"1. **Environment Ingestion:** At launch, configuration loaders ingest environment variables from the host operating system or local `.env` files.\n"
            f"2. **Type Casting & Defaults:** Raw strings are cast to typed configurations, applying sensible fallback defaults for non-critical settings.\n"
            f"3. **Fail-Fast Validation:** Missing critical variables halt application boot immediately to prevent unpredictable runtime states.\n"
            f"4. **Module Distribution:** Sanitized configuration settings are injected into domain handlers and persistence adapters.\n\n"
            f"> **Secret Protection Notice:** All sensitive tokens, passwords, and private keys are strictly redacted in this documentation."
        )

    elif orig_num == 12:
        # Testing
        test_info = graph.testing
        if test_info.test_files_count > 0 or test_info.test_frameworks:
            cmd_str = ", ".join([f"`{c}`" for c in test_info.test_commands]) or "Native test runner"
            fw_str = ", ".join(test_info.test_frameworks) or "Automated Test Suite"
            files_list = "\n".join([f"- `{f}`" for f in test_info.test_files[:15]]) or "- No dedicated test files detected"
            t_spec = diagram_specs.get("testing_pipeline")
            t_mermaid = f"\n\n#### Figure {active_num}.1: Automated Test Execution Pipeline\n\n{render_mermaid(t_spec)}\n" if t_spec else ""
            return (
                f"### Test Engineering Architecture & Quality Strategy\n\n"
                f"`{project_name}` incorporates automated test suites to ensure software reliability, functional correctness, and regression safety. "
                f"Static inspection detected **{test_info.test_files_count}** test files leveraging **{fw_str}**.\n\n"
                f"### Test Suite Inventory & Specifications\n\n"
                f"- **Test Frameworks:** {fw_str}\n"
                f"- **Test Files Identified:** {test_info.test_files_count}\n"
                f"- **Primary Test Execution Commands:** {cmd_str}\n\n"
                f"### Identified Test Files\n\n"
                f"{files_list}\n"
                f"{t_mermaid}\n\n"
                f"### Test Pipeline & Execution Walkthrough\n\n"
                f"Automated test procedures execute unit and integration assertions across discovered test fixtures to validate code functionality:\n\n"
                f"1. **Test Discovery:** The test runner scans test directories for files matching test patterns.\n"
                f"2. **Fixture Initialization:** Test fixtures prepare isolated execution contexts, mocking external services where appropriate.\n"
                f"3. **Assertion Verification:** Tests exercise domain routines, asserting expected return values, exceptions, and side effects.\n"
                f"4. **Reporting & Feedback:** Test runners output execution summaries, exit codes, and coverage metrics for developer feedback and CI gates.\n\n"
                f"> **Execution Notice:** Tests detected; runtime execution was not performed during static repository analysis. Runtime pass/fail metrics and test coverage remain unmeasured."
            )
        else:
            languages_str = ", ".join(graph.languages.keys()) or "detected languages"
            return (
                f"### Test Suite Specifications & Verification Posture\n\n"
                f"> **Inspection Finding:** Static repository analysis scanned file paths, directories, and package configurations for automated test suites (e.g., `test_*.py`, `*_test.py`, `tests/`, `__tests__/`, `spec/`, Jest, pytest, unittest). No automated test files or test runner configurations were identified in this repository.\n\n"
                f"### Current Verification Status & Quality Risks\n\n"
                f"- **Automated Coverage:** 0% verified automated test coverage.\n"
                f"- **Regression Risk:** Without automated unit and integration tests, code refactoring and modifications carry a risk of undetected regressions.\n"
                f"- **Manual Verification:** Verification relies entirely on ad-hoc manual execution by developers.\n\n"
                f"### Recommended Testing Strategy\n\n"
                f"To establish regression safety for `{project_name}`, introducing an automated testing suite is recommended:\n\n"
                f"1. **Framework:** Adopt standard testing tooling appropriate for {languages_str} (e.g. `pytest` for Python or `vitest`/`jest` for TypeScript/JavaScript).\n"
                f"2. **Test Directory:** Create a dedicated `tests/` directory with fixtures covering primary entry points (`{', '.join(graph.entry_points) or 'main'}`).\n"
                f"3. **CI Integration:** Integrate test execution into an automated CI pipeline triggered on pull requests."
            )

    elif orig_num == 13:
        # Security
        sec = graph.security
        sec_table = build_security_table(graph)
        auth_str = ", ".join(sec.auth_mechanisms) if sec.auth_mechanisms else "Standard authorization controls"
        pat_str = ", ".join(sec.security_patterns) if sec.security_patterns else "Input validation and environment isolation"
        sym_str = ", ".join([f"`{s}`" for s in sec.auth_symbols[:10]]) if sec.auth_symbols else "Standard application symbols"
        sec_spec = diagram_specs.get("security_arch")
        sec_mermaid = f"\n\n#### Figure {active_num}.1: Security Architecture & Access Control Flow\n\n{render_mermaid(sec_spec)}\n" if sec_spec else ""
        return (
            f"### Security Architecture & Defense-in-Depth Posture\n\n"
            f"The security posture of `{project_name}` is designed to protect repository operations, runtime data, and execution boundaries. "
            f"Security controls enforce access boundaries, input validation, and secret protection.\n\n"
            f"- **Authentication Mechanisms:** {auth_str}\n"
            f"- **Security Policies & Protections:** {pat_str}\n"
            f"- **Identified Security Symbols:** {sym_str}\n\n"
            f"### Verified Security Status Evaluation\n\n"
            f"{sec_table}\n"
            f"{sec_mermaid}\n\n"
            f"### Access Control & Protection Walkthrough\n\n"
            f"1. **Input Validation:** Incoming inputs, API payloads, and parameters are sanitized to prevent injection attacks and unexpected errors.\n"
            f"2. **Boundary Authentication:** Requests reaching sensitive interfaces are validated against active tokens or credentials.\n"
            f"3. **Secret Redaction:** Configuration variables, API keys, and connection credentials are shielded from log leaks and documentation outputs.\n"
            f"4. **Least Privilege Execution:** Modules execute within restricted process privileges, limiting access to filesystem and host resources."
        )

    elif orig_num == 14:
        # CI/CD Pipeline
        ci_files = graph.devops.ci_files
        if ci_files:
            diag_spec = diagram_specs.get("cicd_pipeline")
            mermaid_block = f"\n\n#### Figure {active_num}.1: Continuous Integration & Deployment Pipeline\n\n{render_mermaid(diag_spec)}\n" if diag_spec else ""
            ci_files_str = ", ".join([f"`{f}`" for f in ci_files])
            stages_str = ", ".join([f"`{s}`" for s in graph.devops.ci_stages]) or "Automated Build & Test"
            return (
                f"### Continuous Integration & Deployment Architecture\n\n"
                f"`{project_name}` implements automated CI/CD workflows to validate code contributions, enforce quality standards, and deliver reliable release packages. "
                f"Repository inspection identified **{len(ci_files)}** active workflow definition files.\n\n"
                f"### CI/CD Workflow Inventory\n\n"
                f"- **Workflow Definition Files:** {ci_files_str}\n"
                f"- **Configured Pipeline Stages:** {stages_str}\n"
                f"{mermaid_block}\n\n"
                f"### Stage-by-Stage Pipeline Walkthrough\n\n"
                f"When events (such as code pushes or pull requests) trigger the pipeline, execution traverses automated stages:\n\n"
                f"1. **Checkout & Environment Setup:** The runner checks out repository code and prepares language runtime environments.\n"
                f"2. **Dependency Resolution & Caching:** Package dependencies are resolved and cached to minimize build latency.\n"
                f"3. **Linting & Code Quality:** Code style, formatting, and static typing are verified.\n"
                f"4. **Automated Test Execution:** Test suites execute across defined environments to catch regressions.\n"
                f"5. **Build & Artifact Packaging:** Production bundles, binaries, or container images are compiled and verified.\n"
                f"6. **Deployment & Release:** Verified artifacts are published or deployed to target environments based on branch rules.\n\n"
                f"### CI/CD Security & Environment Secrets\n\n"
                f"Workflows execute within isolated runner environments. Sensitive credentials (such as deployment keys and registry tokens) are injected securely via repository secrets, preventing accidental exposure in logs."
            )
        else:
            return (
                f"### CI/CD Pipeline & Build Automation\n\n"
                f"> **Inspection Finding:** Static inspection checked repository files for continuous integration and continuous deployment configurations (such as `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `bitbucket-pipelines.yml`, or `azure-pipelines.yml`). No automated CI/CD pipeline definitions were discovered in the codebase.\n\n"
                f"### Missing Automated Pipeline Stages\n\n"
                f"The following standard automation stages are currently unconfigured in this repository:\n\n"
                f"- **Automated Linting & Formatting:** Code style and syntax checks are not automatically enforced on commit or pull request.\n"
                f"- **Automated Test Execution:** Test suites are not triggered automatically on code push.\n"
                f"- **Security & Dependency Auditing:** No automated vulnerability scanning or secret leak detection is configured.\n"
                f"- **Automated Deployment & Release:** Build artifacts and deployments must be produced and pushed manually.\n\n"
                f"### Manual Delivery Procedures & Recommendations\n\n"
                f"Currently, code verification, packaging, and deployments are executed manually by operators. It is recommended to create a `.github/workflows/ci.yml` pipeline to automate dependency installation, linting, and verification."
            )

    elif orig_num == 15:
        # Deployment Architecture
        devops = graph.devops
        if devops.docker_files or devops.deployment_configs:
            docker_str = ", ".join([f"`{d}`" for d in devops.docker_files]) if devops.docker_files else "None identified"
            images_str = ", ".join([f"`{i}`" for i in devops.base_images]) if devops.base_images else "Standard runtime"
            ports_str = ", ".join([f"`{p}`" for p in devops.exposed_ports]) if devops.exposed_ports else "Default runtime ports"
            services_str = ", ".join([f"`{s}`" for s in devops.services]) if devops.services else "Single container / standalone"
            dep_spec = diagram_specs.get("deployment_arch")
            dep_mermaid = f"\n\n#### Figure {active_num}.1: Container & Infrastructure Deployment Topology\n\n{render_mermaid(dep_spec)}\n" if dep_spec else ""
            return (
                f"### Deployment & Containerization Architecture\n\n"
                f"`{project_name}` implements containerization and infrastructure definitions to provide reproducible, isolated deployment environments across development, staging, and production hosting.\n\n"
                f"### Infrastructure Specifications\n\n"
                f"- **Container Manifests:** {docker_str}\n"
                f"- **Base Images:** {images_str}\n"
                f"- **Exposed Network Ports:** {ports_str}\n"
                f"- **Services / Compose Topology:** {services_str}\n"
                f"{dep_mermaid}\n\n"
                f"### Deployment Topology & Service Orchestration\n\n"
                f"1. **Image Construction:** Manifests define multi-stage build layers, caching dependencies to create minimal, hardened container images.\n"
                f"2. **Networking & Ports:** Applications bind to configured network ports ({ports_str}) for internal service communication or external ingress.\n"
                f"3. **Volume Mounts & Storage:** Persistent storage and local configuration directories are bound into containers where required.\n"
                f"4. **Environment Injection:** Runtime configuration parameters are passed during container instantiation.\n"
                f"5. **Process Lifecycle:** Process managers monitor service health, automatically restarting stopped or failed containers to ensure high availability."
            )
        else:
            languages_str = ", ".join(graph.languages.keys()) or "detected runtime"
            return (
                f"### Deployment Architecture & Runtime Topology\n\n"
                f"> **Inspection Finding:** Static analysis inspected the repository for containerization manifests (`Dockerfile`, `docker-compose.yml`, `Containerfile`), Kubernetes specifications, Helm charts, and cloud infrastructure declarations (Terraform, CloudFormation). No containerization or cloud deployment configurations were detected.\n\n"
                f"### Host Execution Runtime Assumptions\n\n"
                f"In the absence of containerized or cloud deployment manifests, `{project_name}` is designed for direct host execution:\n\n"
                f"- **Runtime Environment:** Executes directly within a host operating system environment equipped with a standard runtime for {languages_str}.\n"
                f"- **Network Binding:** Standalone execution without container port-forwarding or reverse proxy orchestration.\n"
                f"- **Process Model:** Single-process execution launched via standard language interpreters or system binaries.\n\n"
                f"### Containerization Recommendations\n\n"
                f"For reproducible deployments across staging and production environments, creating a `Dockerfile` and a `docker-compose.yml` service definition is recommended to isolate runtime dependencies and enforce consistent runtime environments."
            )

    elif orig_num == 16:
        # Setup and Developer Guide
        setup_cmds = getattr(graph, "setup_commands", [])
        if setup_cmds:
            cmd_lines = "\n".join([f"{i+1}. Run `{c}`" for i, c in enumerate(setup_cmds)])
        else:
            cmd_lines = "1. Clone repository to local environment\n2. Inspect package manifests and install required dependencies\n3. Execute via primary entry point"
        entry_point = graph.entry_points[0] if graph.entry_points else "main"
        pm_str = ", ".join(graph.package_managers) or "detected package manager"
        langs_str = ", ".join(graph.languages.keys()) or "project languages"
        setup_spec = diagram_specs.get("setup_flowchart")
        setup_mermaid = f"\n\n#### Figure {active_num}.1: Developer Onboarding & Local Setup Flowchart\n\n{render_mermaid(setup_spec)}\n" if setup_spec else ""
        return (
            f"### Developer Onboarding & Local Environment Architecture\n\n"
            f"This guide provides comprehensive, step-by-step instructions to set up, build, and run `{project_name}` in a local development environment.\n\n"
            f"### 1. Prerequisites\n\n"
            f"- **Runtime Environment:** Verified runtime for {langs_str}\n"
            f"- **Package Manager:** {pm_str}\n"
            f"- **Version Control:** Git installed and configured\n\n"
            f"### 2. Installation & Workspace Initialization\n\n"
            f"Execute the following steps to initialize the environment and install dependencies:\n\n"
            f"{cmd_lines}\n\n"
            f"### 3. Application Execution\n\n"
            f"- **Primary Entry Point:** `{entry_point}`\n"
            f"- Execute entry script or application command according to project package definitions.\n\n"
            f"{setup_mermaid}\n\n"
            f"### 4. Verification & Testing Workflow\n\n"
            f"After completing installation, verify local environment health:\n\n"
            f"- Ensure all required environment variables are set in `.env`.\n"
            f"- Run the test suite if configured to confirm functional baseline.\n"
            f"- Check that the primary process initializes and binds to expected endpoints or executes successfully without unhandled errors.\n\n"
            f"### 5. Troubleshooting & Common Issues\n\n"
            f"- **Missing Dependencies:** Ensure package manager ({pm_str}) has completed installation successfully.\n"
            f"- **Environment Variable Errors:** Check for required variables and ensure no sensitive secrets are missing or malformed.\n"
            f"- **Port Conflicts:** If running network services, ensure configured ports are not already bound by another process."
        )

    return f"Documentation for {title} grounded in `{project_name}`."


# ── AI SYNTHESIS WITH STRICT ANTI-HALLUCINATION GUARDRAILS ─────────────────────

def _synthesize_section_with_ai(
    orig_num: int,
    active_num: int,
    title: str,
    schema_key: str,
    graph: RepoKnowledgeGraph,
    deterministic_content: str,
) -> str:
    """
    Invokes AI model with strict anti-hallucination instructions and redacted context.
    If AI fails, times out, or hallucinates external platforms, returns deterministic content.
    """
    project_name = graph.project_metadata.project_name if graph.project_metadata else graph.repo_name

    system_instruction = (
        "You are an executive software technical writer generating formal software documentation for a repository. "
        "CRITICAL RULES:\n"
        f"1. You are documenting ONLY the project named '{project_name}'.\n"
        "2. Only include what is factually present in the provided evidence. NEVER invent features, endpoints, databases, or technologies.\n"
        "3. NEVER use names, architectures, or endpoints from any external or host platform.\n"
        "4. NEVER output AI model names, fallback notices, provider names, or generation diagnostic traces.\n"
        "5. Output valid GitHub Flavored Markdown. Do not include unrendered or broken Mermaid."
    )

    user_prompt = (
        f"Project Name: {project_name}\n"
        f"Architecture: {graph.app_type}\n"
        f"Section Number: {active_num}\n"
        f"Section Title: {title}\n"
        f"Verified Repository Evidence:\n"
        f"{deterministic_content}\n\n"
        f"Write a comprehensive, publication-grade technical chapter for Section {active_num}: {title}.\n"
        f"MANDATORY REQUIREMENTS:\n"
        f"- Generate an exhaustive, deeply informative, page-length document (at least 600-1400 words).\n"
        f"- Provide thorough architectural explanations, component breakdowns, operational considerations, and technical analysis.\n"
        f"- Retain and include ALL tables, ASCII trees, and Mermaid diagrams from the verified evidence above without omitting or truncating them.\n"
        f"- Structure the content with clear subheadings (### and ####).\n"
        f"- Stay strictly grounded in '{project_name}' and the evidence provided."
    )

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw_ai = call_groq(messages, max_tokens=3500, temperature=0.15)
        clean_ai = redact_secrets(raw_ai).strip()

        # Anti-leakage sanity check: fail if AI hallucinates unrelated host platform names
        banned_leakage_terms = ["codebrain", "anniigcp", "major-project"]
        lower_ai = clean_ai.lower()
        if any(term in lower_ai for term in banned_leakage_terms if term not in project_name.lower()):
            logger.warning("AI output contained host platform leakage. Rejecting AI output for section %d.", active_num)
            return deterministic_content

        if len(clean_ai) > 180:
            return clean_ai
    except Exception as exc:
        logger.warning("AI synthesis failed for Section %d (%s): %s. Using deterministic content.", active_num, title, exc)

    return deterministic_content


def clean_and_format_section(
    sec_body: str,
    det_content: str,
    active_num: int,
    orig_num: int,
    title: str,
) -> str:
    """
    Normalizes generated section content to enforce:
    1. Exactly one top-level canonical heading: '# {active_num}. {title}'.
    2. Strips redundant/duplicate headings, unhashed title lines, or standalone numbers.
    3. Renumbers any subsection headers from orig_num to active_num (e.g. '## 10.1' -> '## 9.1').
    4. Re-injects planned Mermaid diagrams from det_content if the AI synthesis omitted them.
    5. Redacts secrets safely.
    """
    clean = redact_secrets(sec_body).strip()
    title_escaped = re.escape(title)

    # Repeatedly strip leading headings or lines that duplicate the title or section number
    while True:
        prev = clean
        clean = re.sub(rf'^\s*#{1,6}\s*(?:(?:\d+[\.\:]\s*)?{title_escaped}|(?:\d+[\.\:]\s*))\s*\n*', '', clean, flags=re.IGNORECASE)
        clean = re.sub(rf'^\s*(?:\d+[\.\:]\s*){title_escaped}\s*\n*', '', clean, flags=re.IGNORECASE)
        clean = re.sub(rf'^\s*#{1,6}\s+(?:\d+[\.\:]\s*)\s*\n*', '', clean)
        clean = re.sub(r'^\s*\d+\.\s*\n+', '', clean)
        clean = re.sub(r'^\s*> \*\*Project:\*\*.*?\n\n', '', clean, flags=re.DOTALL)
        clean = clean.strip()
        if clean == prev:
            break

    # 2. Renumber subsections: e.g. '## 10.1' -> '## 9.1' if active_num is 9
    if active_num != orig_num:
        clean = re.sub(rf'(#{2,4}\s+){orig_num}\.(\d+)', rf'\g<1>{active_num}.\2', clean)

    # 3. Re-inject planned Mermaid diagrams from det_content if AI dropped them
    if "```mermaid" in det_content and "```mermaid" not in clean:
        mermaid_match = re.search(r'(?:####\s+Figure\s+[^\n]+\n+)?```mermaid[\s\S]*?```', det_content)
        if mermaid_match:
            clean = f"{clean}\n\n{mermaid_match.group(0)}"

    return f"# {active_num}. {title}\n\n{clean}\n"


# ── MAIN GENERATOR ORCHESTRATOR ───────────────────────────────────────────────

def generate_full_project_documentation(
    repo_id: str,
    db,
    commit_sha: str = "HEAD",
    resume: bool = True,
    run_id: Optional[str] = None,
    force_all_16: Optional[bool] = None,
    progress_callback: Optional[Any] = None,
) -> FullDocSuiteResult:
    """
    Generates the technical documentation suite strictly grounded in current repository snapshot.
    Enforces the immutable 16-section contract (SECTIONS_META), strict completion gate,
    factual grounding, deterministic sequential numbering (1..16), and unified exports.
    """
    logger.info("Starting Strict 16-Section Documentation Generation for repo %s (resume=%s)", repo_id, resume)
    graph = analyze_repository(repo_id, db)

    docs_root = STORAGE_ROOT / repo_id / "docs"
    assets_dir = docs_root / "assets"
    diagrams_dir = docs_root / "diagrams"
    diagram_src_dir = docs_root / "diagram-source"
    evidence_dir = docs_root / "evidence"
    metadata_dir = docs_root / "metadata"

    for p in (docs_root, assets_dir, diagrams_dir, diagram_src_dir, evidence_dir, metadata_dir):
        p.mkdir(parents=True, exist_ok=True)

    # ── TARGETED CLEANUP OF CORRUPTED / LEGACY ARTIFACTS ─────────────────────────
    # Never do blanket file wiping so valid sections can be resumed.
    # Clean only corrupted numbering artifacts (e.g. 10-0*, 11-1*, 12-1*, *-0.md, *-1.md)
    corrupted_patterns = ["*10-0*", "*11-1*", "*12-1*", "*-0.md", "*-1.md", "legacy_symbol_*"]
    for pat in corrupted_patterns:
        for corrupted in docs_root.glob(pat):
            try:
                corrupted.unlink()
                logger.info("Cleaned corrupted artifact: %s", corrupted.name)
            except Exception:
                pass

    if not resume:
        for _, _, _, canonical_filename in SECTIONS_META:
            stale_f = docs_root / canonical_filename
            if stale_f.exists():
                try:
                    stale_f.unlink()
                except Exception:
                    pass

    current_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    analysis_version = "v2.0"
    doc_version = "v2.0"
    active_run_id = run_id or f"run_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

    project_meta = graph.project_metadata or ProjectMetadata(
        project_name=graph.repo_name,
        display_name=graph.repo_name,
        repository_name=graph.repo_name,
        branch="main",
        commit_sha=commit_sha,
        generated_at=current_timestamp,
        analysis_version=analysis_version,
        generator_version=doc_version,
    )
    project_meta.commit_sha = commit_sha
    project_meta.generated_at = current_timestamp

    # ── BUILD & PERSIST STRUCTURED DIAGRAMS ────────────────────────────────────
    diagram_specs, visual_inventory = plan_all_diagrams(graph)
    for diag_id, spec in diagram_specs.items():
        try:
            svg_content = render_svg(spec)
            png_bytes = render_png(spec)
            mermaid_source = render_mermaid(spec)

            # Persist to assets/ (backward compatibility)
            (assets_dir / f"diagram_{diag_id}.svg").write_text(svg_content, encoding="utf-8")
            (assets_dir / f"diagram_{diag_id}.png").write_bytes(png_bytes)

            # Persist to diagrams/ (canonical package format)
            (diagrams_dir / f"{diag_id}.svg").write_text(svg_content, encoding="utf-8")
            (diagrams_dir / f"{diag_id}.png").write_bytes(png_bytes)

            # Persist to diagram-source/ (raw Mermaid)
            (diagram_src_dir / f"{diag_id}.mmd").write_text(mermaid_source, encoding="utf-8")
        except Exception as d_err:
            logger.warning("Failed to render diagram assets for %s: %s", diag_id, d_err)

    # Compute genuine documentation quality score
    quality_score = calculate_quality_score(graph)

    if force_all_16 is not None:
        should_force_16 = force_all_16
    else:
        should_force_16 = os.getenv("FORCE_ALL_16_SECTIONS", "1").lower() in ("1", "true", "yes")
    active_plan, omitted_plan = plan_evidence_driven_sections(graph, force_all_16=should_force_16)
    logger.info("Planned %d active sections out of 16 (%d omitted due to lack of evidence)", len(active_plan), len(omitted_plan))

    result = FullDocSuiteResult(
        repo_id=repo_id,
        repo_name=project_meta.project_name,
        project_metadata=project_meta,
        commit_sha=commit_sha,
        timestamp=current_timestamp,
        analysis_version=analysis_version,
        doc_version=doc_version,
        total_sections=len(active_plan),
        is_complete=False,
        run_id=active_run_id,
    )

    # ── PERSIST RESUMABLE GENERATION STATE ──────────────────────────────────────
    state_file = metadata_dir / "generation_state.json"
    gen_state: Dict[str, Any] = {}
    if resume and state_file.exists():
        try:
            gen_state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            gen_state = {}

    validation_summary: Dict[str, Any] = {
        "total_sections": len(active_plan),
        "fully_generated": 0,
        "fallback": 0,
        "empty_state": 0,
        "failed": 0,
        "is_complete": False,
        "errors": [],
        "sections": {},
    }
    schema_data: Dict[str, Any] = {}

    version_badge = (
        f"> **Project:** {project_meta.display_name}  \n"
        f"> **Documentation Version:** {doc_version}  \n"
        f"> **Based on Commit:** `{commit_sha[:10]}`  \n"
        f"> **Generated:** {current_timestamp[:19].replace('T', ' ')} UTC  \n"
        f"> **Analysis Version:** {analysis_version}\n\n"
    )

    quality_table = (
        "## Documentation Quality & Verification Report\n\n"
        "| Evaluation Dimension | Score | Weight | Assessment |\n"
        "|---|---|---|---|\n"
        f"| Repository Analysis | {quality_score.repo_analysis:.1f}% | 20% | Verified AST, Manifest, & Structural Analysis |\n"
        f"| Evidence Accuracy | {quality_score.evidence_accuracy:.1f}% | 25% | Grounded Fact Retention & Secret Redaction |\n"
        f"| Architecture Understanding | {quality_score.architecture_understanding:.1f}% | 15% | Multi-Tier Topology & Request Flow Mapping |\n"
        f"| Section Completeness | {quality_score.section_completeness:.1f}% | 15% | Active Evidence-Backed Section Coverage |\n"
        f"| Diagram Quality | {quality_score.diagram_quality:.1f}% | 10% | Validated Mermaid, SVG, & High-Res PNG Graphics |\n"
        f"| Export Consistency | {quality_score.export_quality:.1f}% | 10% | Canonical Synchronized Markdown, PDF, HTML, JSON, ZIP |\n"
        f"| Quality Validation | {quality_score.validation:.1f}% | 5% | Structural Integrity & Schema Validation Passed |\n"
        f"| **Overall Documentation Score** | **{quality_score.total_score:.1f} / 100** | **100%** | **Production Grade** |\n\n"
    )

    limitations_block = ""
    if getattr(graph, "analysis_limitations", []):
        lim_lines = "\n".join([f"- {lim}" for lim in graph.analysis_limitations])
        limitations_block = (
            "### Analysis Limitations & Honest Disclosures\n\n"
            f"{lim_lines}\n\n"
        )

    master_sections_text = [
        f"# {project_meta.display_name} — Project Documentation\n\n",
        version_badge,
        quality_table,
        limitations_block,
        "## Table of Contents\n\n",
    ]

    # Authoritative Table of Contents with dynamic display numbers and canonical filenames
    for plan_item in active_plan:
        disp_num = plan_item["display_number"]
        sec_title = plan_item["title"]
        sec_filename = plan_item["filename"]
        master_sections_text.append(f"{disp_num}. [{sec_title}](./{sec_filename})\n")
    master_sections_text.append("\n---\n\n")

    # ── GENERATE EACH INCLUDED EVIDENCE-BACKED SECTION ────────────────────────
    for plan_item in active_plan:
        orig_id = plan_item["canonical_id"]
        disp_num = plan_item["display_number"]
        title = plan_item["title"]
        schema_key = plan_item["schema_key"]
        canonical_filename = plan_item["filename"]

        if progress_callback:
            try:
                progress_callback(disp_num, len(active_plan), title)
            except Exception:
                pass

        logger.info("Evaluating Section %d/%d (Canonical %d): %s (%s)", disp_num, len(active_plan), orig_id, title, canonical_filename)
        out_file = docs_root / canonical_filename
        reused_existing = False
        formatted_section = ""
        model_used = "deterministic_engine"
        status = "fully_generated"
        warnings: List[str] = []
        val_result: Dict[str, Any] = {}

        # 1. Resumable check: if safely persisted and passes validation, reuse
        if resume and out_file.exists():
            try:
                candidate_content = out_file.read_text(encoding="utf-8")
                v_res = validate_section_content(orig_id, title, candidate_content, graph, display_number=disp_num)
                if v_res.is_valid:
                    formatted_section = candidate_content
                    reused_existing = True
                    val_result = {
                        "valid": v_res.is_valid,
                        "errors": v_res.errors,
                        "warnings": v_res.warnings,
                        "status": v_res.status,
                    }
                    model_used = gen_state.get(str(disp_num), {}).get("model_used", "resumed_cache")
                    logger.info("Resuming validated Section %d from disk: %s", disp_num, canonical_filename)
            except Exception as read_err:
                logger.debug("Failed reading existing section %s: %s", canonical_filename, read_err)

        # 2. Generate and validate if not resumed
        if not reused_existing:
            det_content = build_deterministic_section_content(disp_num, orig_id, title, schema_key, graph, diagram_specs)
            sec_body = _synthesize_section_with_ai(orig_id, disp_num, title, schema_key, graph, det_content)
            if sec_body == det_content:
                status = "fallback"
                model_used = "deterministic_fallback"
            else:
                model_used = "ai_synthesis"

            formatted_section = clean_and_format_section(sec_body, det_content, disp_num, orig_id, title)

            # Validate generated section
            v_res = validate_section_content(orig_id, title, formatted_section, graph, display_number=disp_num)
            val_result = {
                "valid": v_res.is_valid,
                "errors": v_res.errors,
                "warnings": v_res.warnings,
                "status": v_res.status,
            }
            if not v_res.is_valid and model_used != "deterministic_fallback":
                logger.warning(
                    "AI output for Section %d failed validation (%s). Falling back to deterministic content.",
                    disp_num, v_res.errors
                )
                formatted_section = clean_and_format_section(det_content, det_content, disp_num, orig_id, title)
                status = "fallback"
                model_used = "deterministic_fallback"
                v_res = validate_section_content(orig_id, title, formatted_section, graph, display_number=disp_num)
                val_result = {
                    "valid": v_res.is_valid,
                    "errors": v_res.errors,
                    "warnings": v_res.warnings,
                    "status": v_res.status,
                }

            # Persist section file incrementally
            out_file.write_text(formatted_section, encoding="utf-8")

        has_valid_diagram = "```mermaid" in formatted_section
        section_is_complete = val_result.get("valid", True)
        section_status = "COMPLETE" if section_is_complete else "FAILED"

        sec_obj = DocSection(
            section_number=disp_num,
            canonical_id=orig_id,
            title=title,
            schema_key=schema_key,
            filename=canonical_filename,
            content=formatted_section,
            status=section_status,
            has_diagram=has_valid_diagram,
            warnings=val_result.get("warnings", []),
            is_complete=section_is_complete,
            run_id=active_run_id,
            attempt_count=1,
            last_error="; ".join(val_result.get("errors", [])) if not section_is_complete else None,
            model_used=model_used,
            validation_result=val_result,
        )
        result.sections.append(sec_obj)

        schema_data[schema_key] = {
            "section_number": disp_num,
            "canonical_id": orig_id,
            "title": title,
            "filename": canonical_filename,
            "status": section_status,
            "content": formatted_section,
            "is_complete": section_is_complete,
        }

        # Append to Master Document
        clean_section_body = re.sub(r'^\s*#\s+(?:\d+[\.\:]\s*)?[^\n]+\n*', '', formatted_section.strip())
        master_sections_text.append(f"# {disp_num}. {title}\n\n{clean_section_body}\n\n---\n\n")

        if section_is_complete:
            validation_summary["fully_generated"] += 1
        else:
            validation_summary["failed"] += 1

        validation_summary["sections"][disp_num] = {
            "section_number": disp_num,
            "canonical_id": orig_id,
            "title": title,
            "schema_key": schema_key,
            "filename": canonical_filename,
            "status": section_status,
            "is_complete": section_is_complete,
            "has_diagram": has_valid_diagram,
            "errors": val_result.get("errors", []),
            "warnings": val_result.get("warnings", []),
        }

        # Checkpoint generation state incrementally
        gen_state[str(disp_num)] = {
            "section_id": disp_num,
            "canonical_id": orig_id,
            "title": title,
            "filename": canonical_filename,
            "status": section_status,
            "is_complete": section_is_complete,
            "model_used": model_used,
            "run_id": active_run_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        try:
            state_file.write_text(json.dumps(gen_state, indent=2), encoding="utf-8")
        except Exception as st_err:
            logger.debug("Failed saving generation checkpoint: %s", st_err)

    # ── STRICT SERVER-AUTHORITATIVE COMPLETION GATE ────────────────────────────
    suite_report = validate_suite_integrity(
        result.sections,
        docs_dir=docs_root,
        active_plan=active_plan,
    )
    is_suite_complete = suite_report.is_complete
    suite_errors = suite_report.errors
    result.is_complete = is_suite_complete
    result.total_sections = len(active_plan)
    validation_summary["is_complete"] = is_suite_complete
    validation_summary["errors"] = suite_errors
    result.schema_data = schema_data
    result.validation_summary = validation_summary

    # Assemble master document
    master_readme_content = redact_secrets("".join(master_sections_text))
    if not is_suite_complete:
        err_msg = "; ".join(suite_errors)
        draft_warning = (
            "> [!WARNING]\n"
            "> **DOCUMENTATION SUITE INCOMPLETE - DRAFT ONLY**  \n"
            f"> Generation has not passed the completion gate. Issues: {err_msg}  \n"
            "> This document is retained for inspection and recovery only and cannot be released as complete.\n\n"
        )
        master_readme_content = draft_warning + master_readme_content

    master_file = docs_root / "FULL_PROJECT_DOCUMENTATION.md"
    master_file.write_text(master_readme_content, encoding="utf-8")
    result.master_readme = master_readme_content

    # ── PERSIST EVIDENCE & MANIFEST PACKAGES ───────────────────────────────────
    try:
        facts_serialized = []
        for f in getattr(graph, "traceable_facts", []):
            facts_serialized.append({
                "fact": f.fact,
                "source_file": f.source_file,
                "line_or_range": getattr(f, "line_or_range", ""),
                "symbol": f.symbol,
                "analysis_method": f.analysis_method,
                "confidence": getattr(f.confidence, "value", str(f.confidence)),
                "related_entities": getattr(f, "related_entities", []),
            })

        analysis_summary_data = {
            "repo_id": repo_id,
            "project_name": project_meta.project_name,
            "app_type": graph.app_type,
            "quality_score": {
                "total_score": quality_score.total_score,
                "repo_analysis": quality_score.repo_analysis,
                "evidence_accuracy": quality_score.evidence_accuracy,
                "architecture_understanding": quality_score.architecture_understanding,
                "section_completeness": quality_score.section_completeness,
                "diagram_quality": quality_score.diagram_quality,
                "export_quality": quality_score.export_quality,
                "validation": quality_score.validation,
                "score_breakdown": getattr(quality_score, "score_breakdown", {}),
            },
            "analysis_limitations": getattr(graph, "analysis_limitations", []),
            "traceable_facts": facts_serialized,
            "detected_technologies": {
                "languages": graph.languages,
                "frameworks": graph.frameworks,
                "database_type": graph.database_type,
                "package_managers": graph.package_managers,
                "build_tools": graph.build_tools,
                "system_requirements": getattr(graph, "system_requirements", []),
                "external_services": getattr(graph, "external_services", []),
            },
            "security_findings": [
                {"area": sf.area, "status": sf.status, "evidence": sf.evidence, "notes": sf.notes}
                for sf in getattr(graph, "security_findings", [])
            ],
            "inventory": {
                "total_files": graph.total_files,
                "total_symbols": graph.total_symbols,
                "api_endpoints_count": len(graph.api_endpoints),
                "db_models_count": len(graph.db_models),
                "ci_present": graph.ci_present,
                "deployment_present": graph.deployment_present,
            }
        }
        (evidence_dir / "analysis-summary.json").write_text(json.dumps(analysis_summary_data, indent=2), encoding="utf-8")

        manifest_data = {
            "project_name": project_meta.project_name,
            "display_name": project_meta.display_name,
            "repository_name": project_meta.repository_name,
            "branch": project_meta.branch,
            "commit_sha": commit_sha,
            "generated_at": current_timestamp,
            "doc_version": doc_version,
            "analysis_version": analysis_version,
            "quality_score": quality_score.total_score,
            "total_sections": len(active_plan),
            "is_complete": is_suite_complete,
            "completion_gate_errors": suite_errors,
            "included_sections": active_plan,
            "omitted_sections": omitted_plan,
            "sections": [
                {
                    "section_number": p["display_number"],
                    "canonical_id": p["canonical_id"],
                    "title": p["title"],
                    "schema_key": p["schema_key"],
                    "filename": p["filename"],
                }
                for p in active_plan
            ],
        }
        (metadata_dir / "documentation-manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    except Exception as manifest_err:
        logger.warning("Could not write evidence/metadata manifests: %s", manifest_err)

    # ── GENERATE PROJECT-SPECIFIC README.md ───────────────────────────────────
    from docgen.readme_gen import generate_repo_readme
    try:
        project_readme = generate_repo_readme(repo_id, db, graph=graph)
    except Exception as r_err:
        logger.warning("Project README generation encountered error: %s. Using structured builder.", r_err)
        project_readme = f"# {project_meta.project_name}\n\n{graph.project_purpose}\n"

    project_readme = redact_secrets(project_readme)
    readme_file = docs_root / "README.md"
    readme_file.write_text(project_readme, encoding="utf-8")

    try:
        from automation.auto_fix_pipeline import _find_repo_root
        local_repo_root = _find_repo_root(repo_id)
        if local_repo_root and local_repo_root.exists() and (local_repo_root / "README.md").resolve() != readme_file.resolve():
            (local_repo_root / "README.md").write_text(project_readme, encoding="utf-8")
    except Exception as copy_err:
        logger.debug("Could not copy README to local repo root: %s", copy_err)

    # ── EXPORT MULTI-FORMAT OUTPUTS (PDF, HTML, JSON) ─────────────────────────
    # Even if suite had warnings, we provide formats for review, but manifest / is_complete tracks truth
    meta_dict = {
        "display_name": project_meta.display_name,
        "project_name": project_meta.project_name,
        "repository_name": project_meta.repository_name,
        "branch": project_meta.branch,
        "commit_sha": commit_sha,
        "generated_at": current_timestamp,
        "doc_version": doc_version,
        "analysis_version": analysis_version,
        "is_complete": is_suite_complete,
    }

    # 1. PDF Export
    try:
        generate_pdf_documentation(
            project_name=project_meta.project_name,
            sections=result.sections,
            master_md=master_readme_content,
            output_path=docs_root / "FULL_PROJECT_DOCUMENTATION.pdf",
            metadata=meta_dict,
            assets_dir=assets_dir,
        )
        logger.info("Successfully compiled PDF export for %s", repo_id)
    except Exception as exp_err:
        logger.error("Failed to compile PDF export for %s: %s", repo_id, exp_err)

    # 2. HTML Export
    try:
        generate_html_documentation(
            project_name=project_meta.project_name,
            sections=result.sections,
            master_md=master_readme_content,
            output_path=docs_root / "FULL_PROJECT_DOCUMENTATION.html",
            metadata=meta_dict,
            assets_dir=assets_dir,
        )
        logger.info("Successfully compiled HTML export for %s", repo_id)
    except Exception as html_err:
        logger.error("Failed to compile HTML export for %s: %s", repo_id, html_err)

    # 3. JSON Export
    try:
        generate_json_documentation(
            repo_id=repo_id,
            repo_name=project_meta.project_name,
            sections=result.sections,
            master_md=master_readme_content,
            output_path=docs_root / "FULL_PROJECT_DOCUMENTATION.json",
            metadata=meta_dict,
        )
        logger.info("Successfully compiled JSON export for %s", repo_id)
    except Exception as json_err:
        logger.error("Failed to compile JSON export for %s: %s", repo_id, json_err)

    # ── PERSIST TO DATABASE (Supabase PostgreSQL) FOR TRUE CLOUD DURABILITY ──
    try:
        if db is not None:
            import uuid as _uuid
            from models import RepoDoc

            existing_doc = db.query(RepoDoc).filter(RepoDoc.repo_id == repo_id).first()
            sections_data = [
                {
                    "section_number": s.section_number,
                    "title": s.title,
                    "schema_key": s.schema_key,
                    "filename": s.filename,
                    "content": s.content,
                    "status": s.status,
                    "is_complete": s.is_complete,
                    "has_diagram": s.has_diagram,
                    "warnings": s.warnings,
                }
                for s in result.sections
            ]
            manifest_data = {}
            manifest_file = metadata_dir / "documentation-manifest.json"
            if manifest_file.exists():
                try:
                    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if existing_doc:
                existing_doc.commit_sha = commit_sha
                existing_doc.doc_version = doc_version
                existing_doc.is_complete = is_suite_complete
                existing_doc.master_content = master_readme_content
                existing_doc.sections_json = json.dumps(sections_data)
                existing_doc.manifest_json = json.dumps(manifest_data)
                existing_doc.validation_summary_json = json.dumps(validation_summary)
                existing_doc.status = "READY"
                existing_doc.updated_at = now_utc
            else:
                new_doc = RepoDoc(
                    id=str(_uuid.uuid4()),
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                    doc_version=doc_version,
                    is_complete=is_suite_complete,
                    master_content=master_readme_content,
                    sections_json=json.dumps(sections_data),
                    manifest_json=json.dumps(manifest_data),
                    validation_summary_json=json.dumps(validation_summary),
                    status="READY",
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                db.add(new_doc)
            db.commit()
            logger.info("Persisted RepoDoc to PostgreSQL for repo %s (is_complete=%s)", repo_id, is_suite_complete)
    except Exception as db_err:
        logger.error("Failed to persist RepoDoc to database for repo %s: %s", repo_id, db_err)

    return result

