"""
backend/docgen/schema.py
------------------------
Canonical schemas and constants for the Universal Documentation Subsystem.
Defines the strictly enforced 16-section technical documentation framework,
evidence confidence classification, traceable facts, and QA gates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ── NO-HALLUCINATION CONFIDENCE CLASSIFICATION (REQUIREMENT 3) ────────────────
class ConfidenceLevel(str, Enum):
    CONFIRMED = "CONFIRMED"                      # Direct evidence in code/manifest/config
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"  # Partial evidence without full configuration
    INFERRED = "INFERRED"                        # Logically supported by multiple repository facts
    NOT_DETECTED = "NOT_DETECTED"                # Searched locations and found no evidence
    UNKNOWN = "UNKNOWN"                          # Cannot determine reliably from repo files


# ── EXACT 16 CANONICAL TOP-LEVEL SECTIONS ─────────────────────────────────────
# Single source of truth for backend generation, frontend navigation, TOC,
# Markdown headings, HTML anchors, and PDF bookmarks.
# ── EXACT 16 CANONICAL TOP-LEVEL SECTIONS (IMMUTABLE CONTRACT) ────────────────
# Single source of truth for backend generation, frontend navigation, TOC,
# Markdown headings, HTML anchors, and PDF bookmarks.
CANONICAL_SECTIONS_COUNT = 16

SECTIONS_META = [
    (1, "Project Overview", "projectOverview", "01-project-overview.md"),
    (2, "Technology Stack", "technologyStack", "02-technology-stack.md"),
    (3, "Repository Structure", "repositoryStructure", "03-repository-structure.md"),
    (4, "System Architecture", "systemArchitecture", "04-system-architecture.md"),
    (5, "Modules and Components", "modules", "05-modules-and-components.md"),
    (6, "Classes and Functions", "classesAndFunctions", "06-classes-and-functions.md"),
    (7, "APIs and Interfaces", "apis", "07-apis-and-interfaces.md"),
    (8, "Database and Data Model", "database", "08-database-and-data-model.md"),
    (9, "Database Relationships", "databaseRelationships", "09-database-relationships.md"),
    (10, "Dependencies", "dependencies", "10-dependencies.md"),
    (11, "Configuration and Environment", "configuration", "11-configuration-and-environment.md"),
    (12, "Testing", "testing", "12-testing.md"),
    (13, "Security", "security", "13-security.md"),
    (14, "CI/CD Pipeline", "cicd", "14-ci-cd-pipeline.md"),
    (15, "Deployment Architecture", "deployment", "15-deployment-architecture.md"),
    (16, "Setup and Developer Guide", "setupGuide", "16-setup-and-developer-guide.md"),
]

# Legacy filename compatibility map
LEGACY_FILENAMES_BY_ID = {
    1: "01_project_overview.md",
    2: "02_technology_stack.md",
    3: "03_repository_structure.md",
    4: "04_system_architecture.md",
    5: "05_modules_and_components.md",
    6: "06_classes_and_functions.md",
    7: "07_apis_and_interfaces.md",
    8: "08_database_and_data_model.md",
    9: "09_database_relationships.md",
    10: "10_dependencies.md",
    11: "11_configuration_and_environment.md",
    12: "12_testing.md",
    13: "13_security.md",
    14: "14_cicd_pipeline.md",
    15: "15_deployment_architecture.md",
    16: "16_setup_and_developer_guide.md",
}

DOCUMENTATION_SCHEMA_KEYS = [meta[2] for meta in SECTIONS_META]

DOCUMENTATION_SECTIONS = [
    {
        "id": meta[0],
        "number": meta[0],
        "num": meta[0],
        "title": meta[1],
        "key": meta[2],
        "schema_key": meta[2],
        "filename": meta[3],
        "legacy_filename": LEGACY_FILENAMES_BY_ID.get(meta[0], meta[3]),
    }
    for meta in SECTIONS_META
]

CANONICAL_SECTION_BY_ID: Dict[int, Dict[str, Any]] = {
    sec["id"]: sec for sec in DOCUMENTATION_SECTIONS
}

CANONICAL_SECTION_BY_KEY: Dict[str, Dict[str, Any]] = {
    sec["schema_key"]: sec for sec in DOCUMENTATION_SECTIONS
}


def get_canonical_section(section_id: int) -> Dict[str, Any]:
    """Retrieve canonical section definition by stable integer ID (1..16)."""
    if section_id not in CANONICAL_SECTION_BY_ID:
        raise ValueError(f"Invalid section ID {section_id}. Must be integer between 1 and 16.")
    return CANONICAL_SECTION_BY_ID[section_id]


def resolve_canonical_filename(filename_or_id: Any) -> str:
    """Deterministically map any section ID or legacy filename to canonical filename."""
    if isinstance(filename_or_id, int):
        if filename_or_id in CANONICAL_SECTION_BY_ID:
            return CANONICAL_SECTION_BY_ID[filename_or_id]["filename"]
    if isinstance(filename_or_id, str):
        clean = filename_or_id.strip()
        # Direct match
        for meta in SECTIONS_META:
            if clean == meta[3]:
                return meta[3]
        # Legacy filename match
        for s_id, leg in LEGACY_FILENAMES_BY_ID.items():
            if clean == leg:
                return CANONICAL_SECTION_BY_ID[s_id]["filename"]
        # Numeric prefix match (e.g. "01_...", "10-...")
        m = re.match(r'^(\d+)[-_]', clean)
        if m:
            num = int(m.group(1))
            if num in CANONICAL_SECTION_BY_ID:
                return CANONICAL_SECTION_BY_ID[num]["filename"]
    raise ValueError(f"Cannot resolve canonical filename for: {filename_or_id}")


def is_section_supported_by_evidence(canonical_id: int, graph: Any) -> Tuple[bool, str]:
    """
    Evaluates whether real evidence exists in the repository for a given canonical topic.
    If False, the section is omitted under evidence-based sequential numbering (1..N).
    Never fabricates missing features.
    """
    if canonical_id == 1:
        return (graph.total_files > 0, "Repository has source files")
    elif canonical_id == 2:
        has_tech = bool(graph.languages or graph.frameworks or graph.manifest_dependencies or getattr(graph, "system_requirements", []) or getattr(graph, "external_services", []))
        return (has_tech, "Language or package ecosystem detected" if has_tech else "No programming languages or frameworks detected")
    elif canonical_id == 3:
        has_struct = bool(graph.directory_structure or graph.total_files > 0)
        return (has_struct, "Directory hierarchy detected" if has_struct else "No directory hierarchy found")
    elif canonical_id == 4:
        has_arch = bool(graph.entry_points or graph.directory_structure or graph.total_symbols > 0)
        return (has_arch, "System components and entry points detected" if has_arch else "No application architecture elements discovered")
    elif canonical_id == 5:
        has_mod = bool(graph.directory_structure and len(graph.directory_structure) > 0)
        return (has_mod, "Source modules detected" if has_mod else "No module structure detected")
    elif canonical_id == 6:
        has_syms = bool(graph.functions or graph.classes)
        return (has_syms, "AST classes or functions detected" if has_syms else "No AST classes or functions discovered")
    elif canonical_id == 7:
        has_api = bool(graph.api_endpoints and len(graph.api_endpoints) > 0)
        return (has_api, f"{len(graph.api_endpoints)} API endpoints detected" if has_api else "No HTTP/REST routes or network endpoints implemented in repository")
    elif canonical_id == 8:
        has_db = bool(graph.db_present or (graph.db_models and len(graph.db_models) > 0))
        return (has_db, f"{len(graph.db_models)} persistent data models detected" if has_db else "No database persistence, ORM models, or SQL migrations detected in repository")
    elif canonical_id == 9:
        has_rels = bool(graph.db_models and any(m.relationships for m in graph.db_models))
        return (has_rels, "Relational schema associations or foreign keys detected" if has_rels else "No relational foreign keys, ORM associations, or join constraints detected among models")
    elif canonical_id == 10:
        has_deps = bool(graph.manifest_dependencies or getattr(graph, "system_requirements", []) or getattr(graph, "external_services", []))
        return (has_deps, f"{len(graph.manifest_dependencies)} dependencies detected" if has_deps else "No package manifests or external library dependencies declared")
    elif canonical_id == 11:
        has_cfg = bool(getattr(graph, "config_details", []) or (graph.security and graph.security.config_vars))
        return (has_cfg, "Environment or configuration variables detected" if has_cfg else "No environment variables or runtime configuration files detected")
    elif canonical_id == 12:
        has_tests = bool(graph.testing.test_files_count > 0 or graph.testing.test_frameworks)
        return (has_tests, f"{graph.testing.test_files_count} test files detected" if has_tests else "No automated test files or testing framework configurations detected")
    elif canonical_id == 13:
        sec = graph.security
        has_sec = bool(getattr(graph, "security_findings", []) or sec.auth_symbols or sec.auth_mechanisms or sec.security_patterns)
        return (has_sec, "Security controls or authentication symbols detected" if has_sec else "No security controls, auth handlers, or encryption symbols detected")
    elif canonical_id == 14:
        has_ci = bool(graph.ci_present or (graph.devops.ci_files and len(graph.devops.ci_files) > 0))
        return (has_ci, "CI/CD workflow definitions detected" if has_ci else "No CI/CD pipeline definitions or workflow files detected in repository")
    elif canonical_id == 15:
        has_dep = bool(graph.deployment_present or graph.devops.docker_files or graph.devops.services or graph.devops.base_images or graph.devops.deployment_configs)
        return (has_dep, "Container or deployment configurations detected" if has_dep else "No Dockerfiles, container manifests, or deployment configurations detected in repository")
    elif canonical_id == 16:
        has_setup = bool(graph.package_managers or graph.build_tools or graph.entry_points or getattr(graph, "setup_commands", []))
        return (has_setup, "Installation commands or build tooling detected" if has_setup else "No setup commands, package managers, or entry points detected")
    return (False, "Unknown canonical topic")


def plan_evidence_driven_sections(graph: Any, force_all_16: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Evaluates candidate topics 1..16 against repository evidence.
    Returns:
      included: List of active sections with sequentially assigned display numbers (1..N).
      omitted: List of omitted sections with reasons.
    """
    included = []
    omitted = []
    disp_num = 1

    for meta in SECTIONS_META:
        orig_id, title, schema_key, canonical_filename = meta
        if force_all_16:
            is_supported, reason = True, "Forced inclusion"
        else:
            is_supported, reason = is_section_supported_by_evidence(orig_id, graph)

        if is_supported:
            included.append({
                "canonical_id": orig_id,
                "display_number": disp_num,
                "title": title,
                "schema_key": schema_key,
                "filename": canonical_filename,
                "evidence_reason": reason,
            })
            disp_num += 1
        else:
            omitted.append({
                "canonical_id": orig_id,
                "title": title,
                "schema_key": schema_key,
                "filename": canonical_filename,
                "reason": reason,
            })

    return included, omitted


@dataclass
class ProjectMetadata:
    """Dynamic project identity derived strictly from repository evidence."""
    project_name: str
    display_name: str
    repository_name: str
    repository_owner: str = "Unknown"
    repository_url: str = ""
    source_type: str = "upload"  # "upload" | "github"
    branch: str = "main"
    commit_sha: str = "HEAD"
    version_or_tag: str = "1.0.0"
    primary_languages: List[str] = field(default_factory=list)
    project_type: str = ""
    # Explicit Generation Context (Section 1)
    repository_id: str = ""
    repository_source: str = "upload"  # "upload" | "github"
    snapshot_id: str = ""
    analysis_id: str = ""
    generation_id: str = ""
    generated_at: str = ""
    generator_version: str = "v2.0"
    analysis_version: str = "v2.0"


@dataclass
class ProjectClassification:
    """Multi-dimensional evidence-based project classification."""
    primary: str
    secondary: List[str] = field(default_factory=list)
    architecture_style: str = "Modular Architecture"
    confidence: str = ConfidenceLevel.CONFIRMED.value
    evidence_summary: str = ""


@dataclass
class CodeRelationship:
    """Verified code or architectural relationship backed by static/AST analysis."""
    source_id: str
    target_id: str
    relation_type: str  # "contains", "imports", "calls", "inherits", "implements", "persists_to", "references", "exposes", "invokes", "communicates_with"
    evidence_type: str  # "ast_call", "ast_import", "manifest", "route_handler", "orm_fk", "docker_compose", "ci_stage"
    source_file: str = ""
    confidence: str = ConfidenceLevel.CONFIRMED.value
    label: str = ""


@dataclass
class SectionEligibility:
    """Rigorous evaluation of whether a section contains real repository evidence."""
    section_number: int
    title: str
    schema_key: str
    present: bool
    meaningful_content: bool
    evidence_count: int
    confidence: str  # ConfidenceLevel
    reason: str


@dataclass
class TraceableFact:
    """
    Evidence Traceability (Requirement 4).
    Retains verified evidence for claims without exposing internal chunk IDs.
    """
    fact: str
    source_file: str = ""
    line_or_range: str = ""
    symbol: str = ""
    analysis_method: str = "static_ast"  # "manifest_inspection", "ast_analysis", "regex_route", "devops_scan"
    confidence: str = ConfidenceLevel.CONFIRMED.value
    related_entities: List[str] = field(default_factory=list)


@dataclass
class EvidenceRecord:
    """Traceable evidence backing an architectural or technical fact."""
    claim: str
    source_type: str  # "manifest", "source_code", "config", "docker", "ci", "test", "metadata", "readme"
    source_file: str
    source_location: str = ""
    evidence: str = ""
    confidence: float = 1.0
    confidence_level: str = ConfidenceLevel.CONFIRMED.value
    symbol: str = ""
    analysis_method: str = "static_analysis"
    related_entities: List[str] = field(default_factory=list)


@dataclass
class DocumentationQualityScore:
    """
    Quality Score model (Requirement 25).
    Evaluates analysis, accuracy, architecture, completeness, diagrams, exports, validation.
    """
    repo_analysis: float = 20.0        # max 20%
    evidence_accuracy: float = 25.0    # max 25%
    architecture_understanding: float = 15.0  # max 15%
    section_completeness: float = 15.0 # max 15%
    diagram_quality: float = 10.0      # max 10%
    export_quality: float = 10.0       # max 10%
    validation: float = 5.0            # max 5%
    total_score: float = 100.0         # Out of 100
    limitations: List[str] = field(default_factory=list)
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class DiagramNode:
    id: str
    label: str
    sublabel: str = ""
    kind: str = "generic"  # "client", "frontend", "backend", "database", "cache", "service", "external", "ci", "step"
    parent_id: Optional[str] = None


@dataclass
class DiagramEdge:
    source: str
    target: str
    label: str = ""
    style: str = "solid"
    relation_type: str = "connects"  # "calls", "imports", "persists_to", "exposes", "inherits", "subsystem"


@dataclass
class DiagramSubgraph:
    id: str
    label: str
    node_ids: List[str]


@dataclass
class DiagramSpec:
    """Deterministic, structured diagram specification."""
    diagram_id: str
    title: str
    diagram_type: str  # "architecture", "data_flow", "er", "cicd", "module_relationships", "tree"
    nodes: List[DiagramNode]
    edges: List[DiagramEdge]
    subgraphs: List[DiagramSubgraph] = field(default_factory=list)
    hierarchy_direction: str = "TB"  # "TB" (Top->Down) or "LR" (Left->Right)


@dataclass
class FigureSpec:
    """Metadata and paths for a rendered figure in the document."""
    diagram_id: str
    figure_number: str  # e.g., "Figure 4.1"
    title: str
    caption: str
    explanation: str
    svg_filename: str
    png_filename: str
    diagram_spec: Optional[DiagramSpec] = None


@dataclass
class TableSpec:
    """Structured data table specification with dynamic table numbering."""
    table_number: str  # e.g., "Table 2.1"
    title: str
    headers: List[str]
    rows: List[List[str]]
    widths: Optional[List[float]] = None


@dataclass
class DocSection:
    section_number: int  # Strict canonical 1..16 section number
    title: str
    schema_key: str
    filename: str
    content: str
    canonical_id: int = 1    # Canonical 1..16 number
    intro_paragraphs: List[str] = field(default_factory=list)
    detailed_prose: str = ""
    tables: List[TableSpec] = field(default_factory=list)
    figures: List[FigureSpec] = field(default_factory=list)
    status: str = "fully_generated"  # "fully_generated" | "fallback" | "failed" | "pending"
    is_complete: bool = False
    has_diagram: bool = False
    warnings: List[str] = field(default_factory=list)
    diagram_specs: List[DiagramSpec] = field(default_factory=list)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    traceable_facts: List[TraceableFact] = field(default_factory=list)
    run_id: str = ""
    attempt_count: int = 1
    last_error: Optional[str] = None
    model_used: str = ""
    updated_at: str = ""
    validation_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QAValidationReport:
    """Comprehensive QA gate report auditing content, evidence, diagrams, and exports."""
    project_name: str
    timestamp: str
    content_accuracy: str = "PASS"
    evidence_validation: str = "PASS"
    section_eligibility: str = "PASS"
    diagram_validation: str = "PASS"
    website_rendering: str = "PASS"
    markdown_export: str = "PASS"
    pdf_export: str = "PASS"
    zip_export: str = "PASS"
    visual_parity: str = "PASS"
    checks: List[Dict[str, Any]] = field(default_factory=list)
    skipped_sections_audit: List[Dict[str, str]] = field(default_factory=list)
    diagram_audit: List[Dict[str, Any]] = field(default_factory=list)
    quality_score: Optional[DocumentationQualityScore] = None


@dataclass
class CanonicalDocumentModel:
    """
    Single source of truth for the entire documentation suite.
    Consumed identically by Website, Markdown, PDF, and ZIP renderers.
    """
    repo_id: str
    repo_name: str
    project_metadata: ProjectMetadata
    classification: ProjectClassification
    commit_sha: str = "HEAD"
    timestamp: str = ""
    doc_version: str = "v2.0"
    analysis_version: str = "v2.0"
    cover_title: str = "TECHNICAL SPECIFICATION & ARCHITECTURE SUITE"
    executive_summary: str = ""
    sections: List[DocSection] = field(default_factory=list)
    qa_report: Optional[QAValidationReport] = None
    quality_score: Optional[DocumentationQualityScore] = None
    all_diagram_specs: Dict[str, DiagramSpec] = field(default_factory=dict)
    all_figures: List[FigureSpec] = field(default_factory=list)
    analysis_limitations: List[str] = field(default_factory=list)


@dataclass
class FullDocSuiteResult:
    repo_id: str
    repo_name: str
    project_metadata: Optional[ProjectMetadata] = None
    commit_sha: str = "HEAD"
    timestamp: str = ""
    analysis_version: str = "v2.0"
    doc_version: str = "v2.0"
    sections: List[DocSection] = field(default_factory=list)
    schema_data: Dict[str, Any] = field(default_factory=dict)
    master_readme: str = ""
    total_sections: int = 16
    is_complete: bool = False
    status: str = "IN_PROGRESS"  # "COMPLETE" | "PARTIAL" | "FAILED" | "IN_PROGRESS"
    run_id: str = ""
    validation_summary: Dict[str, Any] = field(default_factory=dict)
    canonical_doc: Optional[CanonicalDocumentModel] = None
    qa_report: Optional[QAValidationReport] = None
    quality_score: Optional[DocumentationQualityScore] = None
