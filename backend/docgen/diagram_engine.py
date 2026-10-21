"""
backend/docgen/diagram_engine.py
--------------------------------
Structured Diagram Architecture for Universal Documentation.
Translates verified repository evidence into a canonical DiagramSpec, then
deterministically renders it to standalone SVG, high-resolution PNG (for PDF),
and validated Mermaid (for frontend UI).
Raw Mermaid is NEVER exposed directly in PDF or final visual exports.
"""
from __future__ import annotations

import io
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from docgen.schema import (
    DiagramEdge,
    DiagramNode,
    DiagramSpec,
    DiagramSubgraph,
)


# ── COLOR PALETTES FOR DIAGRAM NODES ───────────────────────────────────────────
KIND_COLORS: Dict[str, Dict[str, Any]] = {
    "client": {
        "fill": (245, 158, 11),       # Amber
        "stroke": (217, 119, 6),
        "text": (255, 255, 255),
        "hex_fill": "#f59e0b",
        "hex_stroke": "#d97706",
        "hex_bg": "#1e1b18",
    },
    "frontend": {
        "fill": (14, 165, 233),       # Sky blue
        "stroke": (2, 132, 199),
        "text": (255, 255, 255),
        "hex_fill": "#0ea5e9",
        "hex_stroke": "#0284c9",
        "hex_bg": "#0c1f2e",
    },
    "backend": {
        "fill": (99, 102, 241),       # Indigo
        "stroke": (79, 70, 229),
        "text": (255, 255, 255),
        "hex_fill": "#6366f1",
        "hex_stroke": "#4f46e5",
        "hex_bg": "#18182e",
    },
    "database": {
        "fill": (16, 185, 129),       # Emerald
        "stroke": (5, 150, 105),
        "text": (255, 255, 255),
        "hex_fill": "#10b981",
        "hex_stroke": "#059669",
        "hex_bg": "#0d261e",
    },
    "cache": {
        "fill": (239, 68, 68),        # Red
        "stroke": (220, 38, 38),
        "text": (255, 255, 255),
        "hex_fill": "#ef4444",
        "hex_stroke": "#dc2626",
        "hex_bg": "#2e1212",
    },
    "service": {
        "fill": (168, 85, 247),       # Purple
        "stroke": (147, 51, 234),
        "text": (255, 255, 255),
        "hex_fill": "#a855f7",
        "hex_stroke": "#9333ea",
        "hex_bg": "#22132e",
    },
    "external": {
        "fill": (100, 116, 139),      # Slate
        "stroke": (71, 85, 105),
        "text": (255, 255, 255),
        "hex_fill": "#64748b",
        "hex_stroke": "#475569",
        "hex_bg": "#1a1f26",
    },
    "step": {
        "fill": (59, 130, 246),       # Blue
        "stroke": (37, 99, 235),
        "text": (255, 255, 255),
        "hex_fill": "#3b82f6",
        "hex_stroke": "#2563eb",
        "hex_bg": "#0f1c2e",
    },
    "generic": {
        "fill": (71, 85, 105),
        "stroke": (51, 65, 85),
        "text": (255, 255, 255),
        "hex_fill": "#475569",
        "hex_stroke": "#334155",
        "hex_bg": "#151b24",
    },
}


# ── BUILD DIAGRAM SPECIFICATIONS FROM EVIDENCE ────────────────────────────────

def build_problem_solution_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 1: Problem → Solution Flow."""
    project_name = graph.project_metadata.project_name if graph.project_metadata else graph.repo_name
    app_type = graph.app_type or "Software Solution"
    
    nodes = [
        DiagramNode(id="ps_problem", label="Operational Challenge", sublabel="Domain Inefficiencies", kind="client"),
        DiagramNode(id="ps_limit", label="System Limitations", sublabel="Manual / Unscaled Workflow", kind="cache"),
        DiagramNode(id="ps_solution", label=f"{project_name} Solution", sublabel=app_type, kind="backend"),
        DiagramNode(id="ps_engine", label="Core Engine & Modules", sublabel=f"{graph.total_symbols} Verified Symbols", kind="service"),
        DiagramNode(id="ps_outcome", label="Delivered Outcome", sublabel="Automated & Robust Output", kind="database"),
    ]
    edges = [
        DiagramEdge(source="ps_problem", target="ps_limit", label="Exposes"),
        DiagramEdge(source="ps_limit", target="ps_solution", label="Resolved by"),
        DiagramEdge(source="ps_solution", target="ps_engine", label="Orchestrates"),
        DiagramEdge(source="ps_engine", target="ps_outcome", label="Delivers"),
    ]
    return DiagramSpec(
        diagram_id="problem_solution",
        title=f"{project_name} Problem-Solution Flow",
        diagram_type="workflow",
        nodes=nodes,
        edges=edges,
    )


def build_architecture_diagram_spec(graph) -> Optional[DiagramSpec]:
    """
    Constructs an evidence-backed hierarchical multi-tier system architecture DiagramSpec.
    Grounded strictly in verified components of the analyzed repository.
    Never collapses into a tiny 3-box diagram when rich components are detected.
    """
    nodes: List[DiagramNode] = []
    edges: List[DiagramEdge] = []

    has_frontend = any(f in ("React", "Vue.js", "Angular", "Svelte", "Next.js", "Nuxt") for f in graph.frameworks) or any("frontend" in d.path for d in graph.directory_structure) or any(rf in ("index.html", "src/App.tsx", "src/App.jsx", "src/main.tsx") for rf in [p.path for p in getattr(graph, "repo_files", [])])
    has_backend = any(f in ("FastAPI", "Flask", "Django", "Express", "NestJS", "Spring Boot", "Go Standard Runtime", "Rust Standard Library") for f in graph.frameworks) or bool(graph.api_endpoints) or any("backend" in d.path for d in graph.directory_structure)
    has_db = bool(graph.db_models) or any("database" in d.path or "models" in d.path for d in graph.directory_structure)

    # 1. Monorepo or multi-workspace architecture
    monorepo_workspaces = getattr(graph, "monorepo_workspaces", [])
    if monorepo_workspaces and len(monorepo_workspaces) > 1:
        nodes.append(DiagramNode(id="gateway", label="Monorepo Gateway / Client", sublabel="Root Workspace", kind="client"))
        for idx, ws in enumerate(monorepo_workspaces[:5]):
            ws_id = f"ws_{idx}"
            ws_name = ws.get("name", f"Service {idx+1}")
            ws_type = ws.get("type", "service")
            nodes.append(DiagramNode(id=ws_id, label=ws_name, sublabel=ws.get("path", ""), kind=ws_type))
            nodes.append(DiagramNode(id=f"logic_{idx}", label=f"{ws_name} Logic", sublabel="Internal Modules", kind="backend"))
            edges.append(DiagramEdge(source="gateway", target=ws_id, label="Dispatches"))
            edges.append(DiagramEdge(source=ws_id, target=f"logic_{idx}", label="Executes"))
        if has_db:
            nodes.append(DiagramNode(id="shared_db", label="Database Persistence", sublabel=graph.database_type or "State Store", kind="database"))
            for idx in range(min(2, len(monorepo_workspaces))):
                edges.append(DiagramEdge(source=f"logic_{idx}", target="shared_db", label="ORM / SQL"))
        return DiagramSpec(
            diagram_id="architecture",
            title=f"{graph.repo_name} Multi-Workspace Architecture",
            diagram_type="architecture",
            nodes=nodes,
            edges=edges,
        )

    # 2. Comprehensive Multi-Tier Architecture from repository evidence
    # Tier 1: Presentation & Client
    nodes.append(DiagramNode(id="client", label="Client / Browser", sublabel="HTTP / WebSocket Requests", kind="client"))

    prev_tier_nodes = ["client"]

    if has_frontend:
        fw_fe = next((f for f in graph.frameworks if f in ("React", "Vue.js", "Angular", "Svelte", "Next.js")), "Web Client")
        nodes.append(DiagramNode(id="fe_pages", label=f"UI Pages & Views ({fw_fe})", sublabel="Client Routing & State", kind="frontend"))
        nodes.append(DiagramNode(id="fe_comp", label="Reusable UI Components", sublabel="Component Hierarchy", kind="frontend"))
        edges.append(DiagramEdge(source="client", target="fe_pages", label="Interacts"))
        edges.append(DiagramEdge(source="fe_pages", target="fe_comp", label="Renders"))
        prev_tier_nodes = ["fe_pages", "fe_comp"]

    if has_backend:
        fw_be = next((f for f in graph.frameworks if f in ("FastAPI", "Flask", "Django", "Express", "NestJS", "Spring Boot")), "API Service")
        nodes.append(DiagramNode(id="api_router", label=f"API Routing Layer ({fw_be})", sublabel=f"{len(graph.api_endpoints)} Routes" if graph.api_endpoints else "HTTP Endpoints", kind="service"))
        nodes.append(DiagramNode(id="auth_middleware", label="Middleware & Auth Guards", sublabel=", ".join(graph.security.auth_mechanisms[:2]) or "Request Sanitization", kind="step"))
        
        for p in prev_tier_nodes:
            edges.append(DiagramEdge(source=p, target="api_router", label="REST / JSON"))
        edges.append(DiagramEdge(source="api_router", target="auth_middleware", label="Validates"))

        # Domain / Business Tier
        nodes.append(DiagramNode(id="biz_services", label="Business Domain Services", sublabel="Core Business Logic & Handlers", kind="backend"))
        edges.append(DiagramEdge(source="auth_middleware", target="biz_services", label="Dispatches"))
        
        # Async / Worker / Automation if detected
        if any("task" in d.path or "worker" in d.path or "automation" in d.path for d in graph.directory_structure) or any("celery" in f.lower() for f in graph.frameworks):
            nodes.append(DiagramNode(id="async_worker", label="Async Workers / Tasks", sublabel="Background Processing", kind="service"))
            edges.append(DiagramEdge(source="biz_services", target="async_worker", label="Enqueues"))

        prev_tier_nodes = ["biz_services"]

    # Tier 4: Data & Persistence Tier
    if has_db:
        db_tech = graph.database_type or "Relational Database"
        nodes.append(DiagramNode(id="data_models", label="ORM / Data Models", sublabel=f"{len(graph.db_models)} Entities" if graph.db_models else "Entity Schemas", kind="backend"))
        nodes.append(DiagramNode(id="db_store", label=f"Database ({db_tech})", sublabel="Persistent Storage Engine", kind="database"))
        for p in prev_tier_nodes:
            edges.append(DiagramEdge(source=p, target="data_models", label="Data Access"))
        edges.append(DiagramEdge(source="data_models", target="db_store", label="Reads / Writes"))

    # Tier 5: External Integrations if detected
    ext_integrations = []
    if any("ai" in d.path or "llm" in d.path or "rag" in d.path for d in graph.directory_structure):
        ext_integrations.append(("ext_ai", "AI / LLM Providers", "Language Models & Inference"))
    if any("vector" in d.path or "faiss" in d.path or "chroma" in d.path for d in graph.directory_structure):
        ext_integrations.append(("ext_vector", "Vector Store", "Embeddings Index"))
    if any("storage" in d.path or "s3" in d.path for d in graph.directory_structure):
        ext_integrations.append(("ext_storage", "Disk / Cloud Storage", "Artifact Storage"))

    for ext_id, ext_name, ext_sub in ext_integrations[:2]:
        nodes.append(DiagramNode(id=ext_id, label=ext_name, sublabel=ext_sub, kind="external"))
        target_src = "biz_services" if "biz_services" in [n.id for n in nodes] else "client"
        edges.append(DiagramEdge(source=target_src, target=ext_id, label="Invokes"))

    return DiagramSpec(
        diagram_id="architecture",
        title=f"{graph.repo_name} System Architecture Topology",
        diagram_type="architecture",
        nodes=nodes,
        edges=edges,
    )


def build_er_diagram_spec(graph) -> Optional[DiagramSpec]:
    """
    Builds an ER diagram specification ONLY if database models exist.
    Never fabricates entities if absent.
    """
    if not graph.db_models:
        return None

    nodes: List[DiagramNode] = []
    edges: List[DiagramEdge] = []

    for idx, model in enumerate(graph.db_models[:8]):
        model_id = f"model_{idx}"
        fields_summary = ", ".join(model.fields[:3])
        if len(model.fields) > 3:
            fields_summary += "..."
        nodes.append(DiagramNode(
            id=model_id,
            label=model.model_name,
            sublabel=fields_summary or "Entity Model",
            kind="database",
        ))

        # Relationships
        for rel in model.relationships[:2]:
            target_name = rel.split("->")[-1].strip() if "->" in rel else rel
            # find matching target
            for t_idx, t_m in enumerate(graph.db_models[:8]):
                if t_m.model_name.lower() in target_name.lower() and t_idx != idx:
                    edges.append(DiagramEdge(
                        source=model_id,
                        target=f"model_{t_idx}",
                        label="1:N",
                    ))
                    break

    return DiagramSpec(
        diagram_id="er_diagram",
        title=f"{graph.repo_name} Entity-Relationship Model",
        diagram_type="er",
        nodes=nodes,
        edges=edges,
    )


def build_cicd_diagram_spec(graph) -> Optional[DiagramSpec]:
    """
    Builds a CI/CD pipeline flowchart specification ONLY if CI workflow files exist.
    """
    if not graph.devops.ci_files:
        return None

    nodes: List[DiagramNode] = []
    edges: List[DiagramEdge] = []

    stages = graph.devops.ci_stages or ["checkout", "dependencies", "test", "build"]
    prev_id = None

    nodes.append(DiagramNode(id="push", label="Git Push / PR", sublabel="Trigger", kind="client"))
    prev_id = "push"

    for idx, stage in enumerate(stages[:6]):
        stage_id = f"stage_{idx}"
        nodes.append(DiagramNode(
            id=stage_id,
            label=stage.title(),
            sublabel="Automated Check",
            kind="step",
        ))
        if prev_id:
            edges.append(DiagramEdge(source=prev_id, target=stage_id, label="Pass"))
        prev_id = stage_id

    if graph.devops.docker_files or graph.devops.services:
        deploy_id = "stage_deploy"
        nodes.append(DiagramNode(id=deploy_id, label="Deploy Container", sublabel="Docker / Cloud", kind="backend"))
        edges.append(DiagramEdge(source=prev_id, target=deploy_id, label="Success"))

    return DiagramSpec(
        diagram_id="cicd_pipeline",
        title=f"{graph.repo_name} CI/CD Pipeline Workflow",
        diagram_type="cicd",
        nodes=nodes,
        edges=edges,
    )


def build_workflow_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 1: High-Level Execution Workflow."""
    entry = graph.entry_points[0] if graph.entry_points else "Application Entry"
    nodes = [
        DiagramNode(id="trigger", label="Client / Trigger", sublabel="HTTP / Event / CLI", kind="client"),
        DiagramNode(id="entry", label=f"Entry: {Path(entry).name}", sublabel=entry, kind="service"),
        DiagramNode(id="core", label=f"Core Engine", sublabel=graph.app_type, kind="backend"),
        DiagramNode(id="response", label="Output / Response", sublabel="Payload / State Update", kind="step"),
    ]
    edges = [
        DiagramEdge(source="trigger", target="entry", label="Initiates"),
        DiagramEdge(source="entry", target="core", label="Dispatches"),
        DiagramEdge(source="core", target="response", label="Returns"),
    ]
    if getattr(graph, "database_type", None) or graph.db_models:
        nodes.append(DiagramNode(id="storage", label="Data Store", sublabel=graph.database_type or "Persistence", kind="database"))
        edges.append(DiagramEdge(source="core", target="storage", label="Sync/Read"))

    return DiagramSpec(
        diagram_id="workflow",
        title=f"{graph.repo_name} Execution Workflow",
        diagram_type="workflow",
        nodes=nodes,
        edges=edges,
    )


def build_tech_stack_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 2: Verified Technology Stack Architecture."""
    nodes: List[DiagramNode] = []
    edges: List[DiagramEdge] = []

    # Languages node
    langs = list(graph.languages.keys())[:3]
    nodes.append(DiagramNode(id="langs", label="Languages", sublabel=", ".join(langs) or "Core", kind="client"))

    # Frameworks
    if graph.frameworks:
        nodes.append(DiagramNode(id="frameworks", label="Frameworks", sublabel=", ".join(graph.frameworks[:3]), kind="backend"))
        edges.append(DiagramEdge(source="langs", target="frameworks", label="Implements"))

    # Libraries
    if graph.libraries:
        nodes.append(DiagramNode(id="libs", label="Key Libraries", sublabel=", ".join(graph.libraries[:3]), kind="service"))
        target_src = "frameworks" if graph.frameworks else "langs"
        edges.append(DiagramEdge(source=target_src, target="libs", label="Imports"))

    # Persistence / DB if present
    if getattr(graph, "database_type", None) or graph.db_models:
        db_name = graph.database_type or "Relational Store"
        nodes.append(DiagramNode(id="db_layer", label="Database Layer", sublabel=db_name, kind="database"))
        target_src = "frameworks" if graph.frameworks else "langs"
        edges.append(DiagramEdge(source=target_src, target="db_layer", label="Persists"))

    # Package managers
    if graph.package_managers:
        nodes.append(DiagramNode(id="pkg_mgr", label="Packaging & Build", sublabel=", ".join(graph.package_managers), kind="step"))
        edges.append(DiagramEdge(source="langs", target="pkg_mgr", label="Managed by"))

    return DiagramSpec(
        diagram_id="tech_stack",
        title=f"{graph.repo_name} Technology Stack",
        diagram_type="tech_stack",
        nodes=nodes,
        edges=edges,
    )


def build_repo_structure_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 3: Professional Hierarchical Tree of Repository Structure."""
    if not graph.directory_structure and graph.total_files == 0:
        return None

    root_id = "repo_root"
    nodes = [DiagramNode(id=root_id, label=f"{graph.repo_name}/", sublabel=f"Project Root ({graph.total_files} files)", kind="client")]
    edges = []

    # Map directories and subdirectories
    dir_node_map: Dict[str, str] = {}
    for idx, d in enumerate(graph.directory_structure[:8]):
        dir_id = f"dir_{idx}"
        dir_node_map[d.path] = dir_id
        
        parts = d.path.split("/")
        parent_id = root_id
        if len(parts) > 1:
            parent_path = "/".join(parts[:-1])
            parent_id = dir_node_map.get(parent_path, root_id)

        nodes.append(DiagramNode(
            id=dir_id,
            label=f"{parts[-1]}/",
            sublabel=f"{d.file_count} files",
            kind="service",
        ))
        edges.append(DiagramEdge(source=parent_id, target=dir_id, label="dir"))

        for f_idx, kf in enumerate(d.key_files[:2]):
            file_id = f"f_{idx}_{f_idx}"
            nodes.append(DiagramNode(
                id=file_id,
                label=kf,
                sublabel="Source File",
                kind="step",
            ))
            edges.append(DiagramEdge(source=dir_id, target=file_id, label="file"))

    for idx, ep in enumerate(graph.entry_points[:2]):
        ep_name = Path(ep).name
        if not any(n.label == ep_name for n in nodes):
            ep_id = f"entry_f_{idx}"
            nodes.append(DiagramNode(id=ep_id, label=ep_name, sublabel="Root Entry", kind="step"))
            edges.append(DiagramEdge(source=root_id, target=ep_id, label="entry"))

    return DiagramSpec(
        diagram_id="repo_structure",
        title=f"{graph.repo_name} Repository Structure Tree",
        diagram_type="repo_structure",
        nodes=nodes,
        edges=edges,
    )


def build_data_flow_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 4: Component Data Flow & Processing."""
    nodes = [
        DiagramNode(id="input", label="Input Request", sublabel="Incoming payload", kind="client"),
        DiagramNode(id="validation", label="Schema Validation", sublabel="Data Sanity", kind="step"),
        DiagramNode(id="processing", label="Business Processing", sublabel=graph.app_type, kind="backend"),
    ]
    edges = [
        DiagramEdge(source="input", target="validation", label="Submits"),
        DiagramEdge(source="validation", target="processing", label="Valid"),
    ]

    if getattr(graph, "database_type", None) or graph.db_models:
        nodes.append(DiagramNode(id="storage", label="Data Persistence", sublabel="State Store", kind="database"))
        edges.append(DiagramEdge(source="processing", target="storage", label="Writes"))

    nodes.append(DiagramNode(id="output", label="Response Payload", sublabel="Serialized Result", kind="step"))
    edges.append(DiagramEdge(source="processing", target="output", label="Delivers"))

    return DiagramSpec(
        diagram_id="data_flow",
        title=f"{graph.repo_name} Data Flow Architecture",
        diagram_type="data_flow",
        nodes=nodes,
        edges=edges,
    )


def build_module_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 5: Subsystem & Module Relationships."""
    if len(graph.directory_structure) < 2:
        return None

    nodes = []
    edges = []
    prev_id = None
    for idx, d in enumerate(graph.directory_structure[:5]):
        mod_id = f"mod_{idx}"
        nodes.append(DiagramNode(id=mod_id, label=f"module/{Path(d.path).name}", sublabel=d.purpose[:25], kind="service"))
        if prev_id:
            edges.append(DiagramEdge(source=prev_id, target=mod_id, label="interacts"))
        prev_id = mod_id

    return DiagramSpec(
        diagram_id="modules",
        title=f"{graph.repo_name} Module Relationships",
        diagram_type="modules",
        nodes=nodes,
        edges=edges,
    )


def build_class_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 6: Classes and AST Symbols."""
    if not graph.classes and not graph.functions:
        return None

    nodes = []
    edges = []

    for idx, c in enumerate(graph.classes[:5]):
        cid = f"cls_{idx}"
        methods_str = ", ".join(c.methods[:2]) or "Data Class"
        nodes.append(DiagramNode(id=cid, label=f"class {c.name}", sublabel=methods_str, kind="backend"))

    for idx, f in enumerate(graph.functions[:3]):
        fid = f"fn_{idx}"
        nodes.append(DiagramNode(id=fid, label=f"def {f.name}()", sublabel="Function", kind="service"))
        if nodes and idx < len(graph.classes):
            edges.append(DiagramEdge(source=nodes[0].id, target=fid, label="invokes"))

    return DiagramSpec(
        diagram_id="classes",
        title=f"{graph.repo_name} Classes & Functions",
        diagram_type="classes",
        nodes=nodes,
        edges=edges,
    )


def build_api_tree_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 7: Professional Hierarchical API Route Tree."""
    if not graph.api_endpoints:
        return None

    root_id = "api_root"
    nodes = [DiagramNode(id=root_id, label="API Gateway", sublabel=f"{len(graph.api_endpoints)} Total Routes", kind="client")]
    edges = []

    # Group endpoints by first URL path segment or router tag
    groups: Dict[str, List[Any]] = {}
    for ep in graph.api_endpoints:
        clean_p = ep.path.strip("/")
        group_key = clean_p.split("/")[0] if clean_p else "root"
        groups.setdefault(group_key.title(), []).append(ep)

    for g_idx, (group_name, ep_list) in enumerate(list(groups.items())[:5]):
        grp_id = f"grp_{g_idx}"
        nodes.append(DiagramNode(
            id=grp_id,
            label=f"/{group_name.lower()} Routes",
            sublabel=f"{len(ep_list)} endpoints",
            kind="service",
        ))
        edges.append(DiagramEdge(source=root_id, target=grp_id, label="group"))

        for e_idx, ep in enumerate(ep_list[:3]):
            ep_id = f"ep_{g_idx}_{e_idx}"
            nodes.append(DiagramNode(
                id=ep_id,
                label=f"{ep.http_method} {ep.path[:20]}",
                sublabel=f"{ep.handler_name}()",
                kind="backend",
            ))
            edges.append(DiagramEdge(source=grp_id, target=ep_id, label="route"))

    return DiagramSpec(
        diagram_id="api_tree",
        title=f"{graph.repo_name} API Route Tree",
        diagram_type="api",
        nodes=nodes,
        edges=edges,
    )


def build_api_architecture_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 7: API Request Lifecycle & Architecture Flow."""
    if not graph.api_endpoints:
        return None

    nodes = [
        DiagramNode(id="api_client", label="Client / Frontend", sublabel="HTTP / REST Request", kind="client"),
        DiagramNode(id="api_route", label="Route Dispatcher", sublabel=f"{len(graph.api_endpoints)} Endpoints", kind="service"),
        DiagramNode(id="api_val", label="Schema Validation", sublabel="Pydantic / TypeGuard", kind="step"),
        DiagramNode(id="api_handler", label="Controller / Handler", sublabel="Domain Logic Handler", kind="backend"),
        DiagramNode(id="api_service", label="Service Layer", sublabel="Business Processing", kind="service"),
        DiagramNode(id="api_resp", label="Client Response", sublabel="JSON Payload / Status", kind="step"),
    ]
    edges = [
        DiagramEdge(source="api_client", target="api_route", label="HTTP Call"),
        DiagramEdge(source="api_route", target="api_val", label="Parses"),
        DiagramEdge(source="api_val", target="api_handler", label="Validated"),
        DiagramEdge(source="api_handler", target="api_service", label="Invokes"),
        DiagramEdge(source="api_service", target="api_resp", label="Formats"),
    ]

    if getattr(graph, "database_type", None) or graph.db_models:
        nodes.append(DiagramNode(id="api_db", label="Data Access / Store", sublabel="ORM / SQL Query", kind="database"))
        edges.append(DiagramEdge(source="api_service", target="api_db", label="Persists"))

    return DiagramSpec(
        diagram_id="api_arch",
        title=f"{graph.repo_name} API Request Lifecycle Architecture",
        diagram_type="api",
        nodes=nodes,
        edges=edges,
    )


def build_database_tree_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 8: Professional Hierarchical Database Tree Model."""
    if not graph.db_models:
        return None

    db_tech = graph.database_type or "Relational Store"
    root_id = "db_root"
    nodes = [DiagramNode(id=root_id, label=f"Database: {db_tech}", sublabel=f"{len(graph.db_models)} Persistent Entities", kind="database")]
    edges = []

    for idx, model in enumerate(graph.db_models[:6]):
        tbl_id = f"tbl_{idx}"
        pks = ", ".join(model.primary_keys) if model.primary_keys else "id"
        nodes.append(DiagramNode(
            id=tbl_id,
            label=f"Table: {model.model_name}",
            sublabel=f"PK: ({pks}) - {len(model.fields)} cols",
            kind="backend",
        ))
        edges.append(DiagramEdge(source=root_id, target=tbl_id, label="schema"))

        cols_summary = ", ".join(model.fields[:3])
        if len(model.fields) > 3:
            cols_summary += "..."
        cols_id = f"cols_{idx}"
        nodes.append(DiagramNode(
            id=cols_id,
            label=f"Columns: {model.model_name}",
            sublabel=cols_summary or "Schema attributes",
            kind="step",
        ))
        edges.append(DiagramEdge(source=tbl_id, target=cols_id, label="fields"))

    return DiagramSpec(
        diagram_id="db_tree",
        title=f"{graph.repo_name} Database Schema Tree",
        diagram_type="er",
        nodes=nodes,
        edges=edges,
    )


def build_db_relationships_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 9: Database Entity Relationships & Cardinality."""
    if not graph.db_models or not any(m.relationships for m in graph.db_models):
        return None
    return build_er_diagram_spec(graph)


def build_dependency_tree_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 10: Professional Hierarchical Dependency Tree."""
    if not graph.manifest_dependencies:
        return None

    root_id = "dep_root"
    nodes = [DiagramNode(id=root_id, label="Project Dependencies", sublabel=f"{len(graph.manifest_dependencies)} Packages", kind="client")]
    edges = []

    runtime_deps = [d for d in graph.manifest_dependencies if d.dep_type.lower() in ("runtime", "direct")]
    dev_deps = [d for d in graph.manifest_dependencies if d.dep_type.lower() in ("development", "dev", "peer")]

    if runtime_deps:
        rt_id = "dep_runtime"
        nodes.append(DiagramNode(id=rt_id, label="Runtime Dependencies", sublabel="Production Execution", kind="backend"))
        edges.append(DiagramEdge(source=root_id, target=rt_id, label="requires"))
        for idx, d in enumerate(runtime_deps[:5]):
            pkg_id = f"rt_pkg_{idx}"
            nodes.append(DiagramNode(id=pkg_id, label=d.name, sublabel=d.version or "Package", kind="step"))
            edges.append(DiagramEdge(source=rt_id, target=pkg_id, label="dep"))

    if dev_deps:
        dev_id = "dep_dev"
        nodes.append(DiagramNode(id=dev_id, label="Development & Testing", sublabel="Build & Quality Tooling", kind="service"))
        edges.append(DiagramEdge(source=root_id, target=dev_id, label="dev_tool"))
        for idx, d in enumerate(dev_deps[:4]):
            pkg_id = f"dev_pkg_{idx}"
            nodes.append(DiagramNode(id=pkg_id, label=d.name, sublabel=d.version or "Dev Package", kind="step"))
            edges.append(DiagramEdge(source=dev_id, target=pkg_id, label="tool"))

    return DiagramSpec(
        diagram_id="dep_tree",
        title=f"{graph.repo_name} Dependency Tree",
        diagram_type="dependencies",
        nodes=nodes,
        edges=edges,
    )


def build_dependency_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 10: Package & Dependency Ecosystem."""
    if not graph.manifest_dependencies:
        return None

    nodes = [DiagramNode(id="core", label=graph.repo_name, sublabel="Application Root", kind="client")]
    edges = []

    for idx, d in enumerate(graph.manifest_dependencies[:6]):
        dep_id = f"dep_{idx}"
        nodes.append(DiagramNode(id=dep_id, label=d.name, sublabel=d.version or "Package", kind="service"))
        edges.append(DiagramEdge(source="core", target=dep_id, label="requires"))

    return DiagramSpec(
        diagram_id="dependencies",
        title=f"{graph.repo_name} Dependencies Graph",
        diagram_type="dependencies",
        nodes=nodes,
        edges=edges,
    )


def build_config_flow_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 11: Runtime Configuration Ingestion Flow."""
    if not graph.security.config_vars:
        return None

    nodes = [
        DiagramNode(id="env_file", label=".env / OS Env", sublabel=f"{len(graph.security.config_vars)} Variables", kind="client"),
        DiagramNode(id="loader", label="Config Loader", sublabel="Runtime Ingestion", kind="service"),
        DiagramNode(id="app_cfg", label="Application Context", sublabel="Scoped Settings", kind="backend"),
    ]
    edges = [
        DiagramEdge(source="env_file", target="loader", label="Loads"),
        DiagramEdge(source="loader", target="app_cfg", label="Injects"),
    ]

    return DiagramSpec(
        diagram_id="config_flow",
        title=f"{graph.repo_name} Configuration Flow",
        diagram_type="config",
        nodes=nodes,
        edges=edges,
    )


def build_testing_pipeline_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 12: Automated Test Execution Pipeline."""
    if graph.testing.test_files_count == 0 and not graph.testing.test_frameworks:
        return None

    nodes = [
        DiagramNode(id="test_suite", label="Test Suite", sublabel=f"{graph.testing.test_files_count} Test Files", kind="client"),
        DiagramNode(id="runner", label="Test Runner", sublabel=", ".join(graph.testing.test_frameworks) or "Automated Runner", kind="service"),
        DiagramNode(id="report", label="Test Report", sublabel="Assertions & Coverage", kind="step"),
    ]
    edges = [
        DiagramEdge(source="test_suite", target="runner", label="Executes"),
        DiagramEdge(source="runner", target="report", label="Generates"),
    ]

    return DiagramSpec(
        diagram_id="testing_pipeline",
        title=f"{graph.repo_name} Testing Pipeline",
        diagram_type="testing",
        nodes=nodes,
        edges=edges,
    )


def build_security_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 13: Security Architecture & Access Control Flow."""
    sec = graph.security
    if not sec.auth_symbols and not sec.auth_mechanisms and not sec.security_patterns:
        return None

    nodes = [
        DiagramNode(id="client", label="Client Request", sublabel="Credentials / Token", kind="client"),
        DiagramNode(id="guard", label="Security Guard", sublabel=", ".join(sec.auth_mechanisms[:2]) or "Auth Filter", kind="service"),
        DiagramNode(id="resource", label="Protected Resource", sublabel="Authorized Context", kind="backend"),
    ]
    edges = [
        DiagramEdge(source="client", target="guard", label="Authenticates"),
        DiagramEdge(source="guard", target="resource", label="Grants Access"),
    ]

    return DiagramSpec(
        diagram_id="security_arch",
        title=f"{graph.repo_name} Security & Auth Flow",
        diagram_type="security",
        nodes=nodes,
        edges=edges,
    )


def build_deployment_diagram_spec(graph) -> Optional[DiagramSpec]:
    """Section 15: Infrastructure & Deployment Topology."""
    dev = graph.devops
    if not dev.docker_files and not dev.services and not dev.base_images and not dev.deployment_configs:
        return None

    nodes = [DiagramNode(id="ingress", label="Internet / Gateway", sublabel="Traffic Router", kind="client")]
    edges = []

    if dev.services:
        for idx, s in enumerate(dev.services[:3]):
            sid = f"svc_{idx}"
            nodes.append(DiagramNode(id=sid, label=f"Container: {s}", sublabel="Deployed Service", kind="backend"))
            edges.append(DiagramEdge(source="ingress", target=sid, label="Forwards"))
    else:
        nodes.append(DiagramNode(id="container", label="Docker Container", sublabel=", ".join(dev.base_images[:2]) or "Container Image", kind="backend"))
        edges.append(DiagramEdge(source="ingress", target="container", label="Exposes Port"))

    return DiagramSpec(
        diagram_id="deployment_arch",
        title=f"{graph.repo_name} Deployment Topology",
        diagram_type="deployment",
        nodes=nodes,
        edges=edges,
    )


def build_setup_flowchart_spec(graph) -> Optional[DiagramSpec]:
    """Section 16: Developer Onboarding & Local Setup Flowchart."""
    cmds = getattr(graph, "setup_commands", []) or ["Clone Repo", "Install Dependencies", "Run Application"]
    nodes = []
    edges = []
    prev_id = None

    for idx, c in enumerate(cmds[:4]):
        step_id = f"step_{idx}"
        clean_cmd = re.sub(r'[\'\"`\[\]\(\)\{\}]', '', str(c)).strip()[:24] or "Execute"
        nodes.append(DiagramNode(id=step_id, label=f"Step {idx+1}: {clean_cmd}", sublabel="Terminal Command", kind="step"))
        if prev_id:
            edges.append(DiagramEdge(source=prev_id, target=step_id, label="Next"))
        prev_id = step_id

    entry = graph.entry_points[0] if graph.entry_points else "main"
    nodes.append(DiagramNode(id="ready", label="Application Running", sublabel=f"Entry: {Path(entry).name}", kind="backend"))
    if prev_id:
        edges.append(DiagramEdge(source=prev_id, target="ready", label="Launch"))

    return DiagramSpec(
        diagram_id="setup_flowchart",
        title=f"{graph.repo_name} Local Setup Flowchart",
        diagram_type="setup",
        nodes=nodes,
        edges=edges,
    )


# ── DIAGRAM QUALITY GATE & SYNTAX VALIDATION ──────────────────────────────────
VALID_MERMAID_TYPES = (
    "graph td", "graph lr", "graph tb", "graph rl",
    "flowchart td", "flowchart lr", "flowchart tb", "flowchart rl",
    "sequencediagram", "classdiagram", "erdiagram",
    "statediagram", "statediagram-v2", "gantt", "pie", "gitgraph", "quadrantchart",
    "c4context", "mindmap", "timeline", "block"
)


def validate_mermaid_syntax(chart_code: str) -> Tuple[bool, str]:
    if not chart_code or not chart_code.strip():
        return False, "Empty Mermaid chart code."
    # Strip markdown code fences if present
    clean_code = chart_code.strip()
    clean_code = re.sub(r'^```(?:mermaid)?\s*', '', clean_code, flags=re.IGNORECASE)
    clean_code = re.sub(r'\s*```$', '', clean_code)
    lines = [l.strip() for l in clean_code.strip().splitlines() if l.strip() and not l.strip().startswith("%%")]
    if not lines:
        return False, "Mermaid code contains only comments or whitespace."
    first_line = lines[0].lower().replace(" ", "")
    has_valid_header = any(first_line.startswith(t.replace(" ", "")) for t in VALID_MERMAID_TYPES)
    if not has_valid_header:
        return False, f"Invalid or missing Mermaid diagram header: '{lines[0]}'."
    if len(lines) < 2:
        return False, "Mermaid diagram is incomplete (fewer than 2 statements)."
    for opener, closer in [("[", "]"), ("(", ")"), ("{", "}")]:
        if clean_code.count(opener) != clean_code.count(closer):
            return False, f"Unbalanced brackets in Mermaid diagram: '{opener}' vs '{closer}'."
    if clean_code.count('"') % 2 != 0:
        return False, "Unbalanced double quotes in Mermaid diagram."
    return True, ""


def validate_diagram_spec(spec: DiagramSpec) -> Tuple[bool, List[str]]:
    """
    Enforces Diagram Quality Gate (Section 16):
    - Must have at least 1 node
    - No duplicate node IDs
    - No accidental self-loops (source == target)
    - No broken arrows (all edge endpoints must reference valid nodes)
    - No blank/empty node labels
    - Strictly valid Mermaid syntax
    """
    errors: List[str] = []
    if not spec or not spec.nodes:
        errors.append("Diagram has no nodes.")
        return False, errors

    node_ids = set()
    for n in spec.nodes:
        if not n.id or not n.id.strip():
            errors.append("Found node with empty ID.")
        elif n.id in node_ids:
            errors.append(f"Duplicate node ID detected: '{n.id}'.")
        else:
            node_ids.add(n.id)

        if not n.label or not n.label.strip():
            errors.append(f"Node '{n.id}' has an empty label.")

    for edge in spec.edges:
        if edge.source == edge.target:
            errors.append(f"Self-loop detected on node '{edge.source}'.")
        if edge.source not in node_ids:
            errors.append(f"Broken edge source: '{edge.source}' does not exist in nodes.")
        if edge.target not in node_ids:
            errors.append(f"Broken edge target: '{edge.target}' does not exist in nodes.")

    # Validate Mermaid rendering syntax
    mermaid_code = render_mermaid(spec)
    is_valid_mermaid, mermaid_err = validate_mermaid_syntax(mermaid_code)
    if not is_valid_mermaid:
        errors.append(f"Mermaid syntax error: {mermaid_err}")

    return len(errors) == 0, errors


# ── MASTER DIAGRAM PLANNER ───────────────────────────────────────────────────

def plan_all_diagrams(graph) -> Tuple[Dict[str, DiagramSpec], Dict[str, Any]]:
    """
    Deterministically evaluates repository evidence and constructs all supported
    diagram specifications across the canonical 16 sections.
    Passes each candidate through the Diagram Quality Gate before approval.
    Returns:
      - specs: Map of diagram_id -> DiagramSpec
      - visual_inventory: Diagnostics with Available, Generated, and Skipped + Reason
    """
    candidates = [
        ("workflow", build_workflow_diagram_spec, "Execution Workflow"),
        ("problem_solution", build_problem_solution_diagram_spec, "Problem-Solution Flow"),
        ("tech_stack", build_tech_stack_diagram_spec, "Technology Stack"),
        ("repo_structure", build_repo_structure_diagram_spec, "Repository Structure Tree"),
        ("architecture", build_architecture_diagram_spec, "System Architecture Topology"),
        ("data_flow", build_data_flow_diagram_spec, "Component Data Flow"),
        ("modules", build_module_diagram_spec, "Module Relationships"),
        ("classes", build_class_diagram_spec, "Classes & Functions"),
        ("api_tree", build_api_tree_diagram_spec, "API Route Tree"),
        ("api_arch", build_api_architecture_diagram_spec, "API Routing Architecture"),
        ("db_tree", build_database_tree_diagram_spec, "Database Schema Tree"),
        ("er_diagram", build_er_diagram_spec, "Database ER Model"),
        ("db_relationships", build_db_relationships_diagram_spec, "Database Relationships"),
        ("dep_tree", build_dependency_tree_diagram_spec, "Dependency Tree"),
        ("dependencies", build_dependency_diagram_spec, "Dependencies Graph"),
        ("config_flow", build_config_flow_diagram_spec, "Configuration Flow"),
        ("testing_pipeline", build_testing_pipeline_diagram_spec, "Testing Pipeline"),
        ("security_arch", build_security_diagram_spec, "Security Architecture"),
        ("cicd_pipeline", build_cicd_diagram_spec, "CI/CD Pipeline"),
        ("deployment_arch", build_deployment_diagram_spec, "Deployment Architecture"),
        ("setup_flowchart", build_setup_flowchart_spec, "Setup Flowchart"),
    ]

    specs: Dict[str, DiagramSpec] = {}
    inventory: Dict[str, Any] = {
        "total_evaluated": len(candidates),
        "generated": [],
        "skipped": [],
    }

    for diag_id, builder_fn, name in candidates:
        try:
            spec = builder_fn(graph)
            if spec and spec.nodes:
                is_valid, errors = validate_diagram_spec(spec)
                if is_valid:
                    specs[diag_id] = spec
                    inventory["generated"].append({
                        "id": diag_id,
                        "name": name,
                        "node_count": len(spec.nodes),
                        "edge_count": len(spec.edges)
                    })
                else:
                    inventory["skipped"].append({
                        "id": diag_id,
                        "name": name,
                        "reason": f"Quality gate rejected diagram: {'; '.join(errors)}"
                    })
            else:
                inventory["skipped"].append({
                    "id": diag_id,
                    "name": name,
                    "reason": "No evidence present in analyzed repository"
                })
        except Exception as exc:
            inventory["skipped"].append({
                "id": diag_id,
                "name": name,
                "reason": f"Analysis error: {exc}"
            })

    return specs, inventory


# ── MULTI-FORMAT DETERMINISTIC RENDERERS ──────────────────────────────────────

def _sanitize_mermaid_label(text: str) -> str:
    if not text:
        return ""
    s = str(text).replace('"', "'").replace('`', "'")
    s = s.replace('[', '(').replace(']', ')')
    s = s.replace('{', '(').replace('}', ')')
    s = s.replace('•', '-')
    s = re.sub(r'<(?!br\s*/?>)[^>]+>', '', s)
    return s.strip()


def render_mermaid(spec: DiagramSpec) -> str:
    """Renders DiagramSpec to clean, strictly valid Mermaid syntax for frontend rendering."""
    lines = ["```mermaid", "flowchart TD"]
    for node in spec.nodes:
        clean_id = re.sub(r'[^a-zA-Z0-9_]', '_', str(node.id or "node"))
        clean_label = _sanitize_mermaid_label(node.label)
        if node.sublabel:
            clean_sub = _sanitize_mermaid_label(node.sublabel)
            lines.append(f'    {clean_id}["{clean_label}<br/>{clean_sub}"]')
        else:
            lines.append(f'    {clean_id}["{clean_label}"]')

    for edge in spec.edges:
        clean_src = re.sub(r'[^a-zA-Z0-9_]', '_', str(edge.source or "src"))
        clean_tgt = re.sub(r'[^a-zA-Z0-9_]', '_', str(edge.target or "tgt"))
        if edge.label:
            clean_lbl = _sanitize_mermaid_label(edge.label).replace('|', '/')
            lines.append(f"    {clean_src} -->|{clean_lbl}| {clean_tgt}")
        else:
            lines.append(f"    {clean_src} --> {clean_tgt}")

    lines.append("```")
    return "\n".join(lines)


def render_svg(spec: DiagramSpec, width: int = 800, height: Optional[int] = None) -> str:
    """
    Renders DiagramSpec into a modern, responsive, standalone SVG vector graphic.
    Zero external dependencies. Beautiful dark-theme styling suitable for web and presentation.
    """
    num_nodes = len(spec.nodes)
    if num_nodes == 0:
        return '<svg width="100" height="40"></svg>'

    # Layout calculation (Horizontal / Tiered layout)
    # Group nodes into tiers or flow sequence
    node_w = 170
    node_h = 60
    pad_x = 40
    pad_y = 60

    # Arrange in a grid: up to 3 columns
    cols = min(3, max(1, num_nodes))
    rows = math.ceil(num_nodes / cols)

    actual_w = max(width, cols * (node_w + pad_x) + pad_x)
    actual_h = max(height or 0, rows * (node_h + pad_y) + pad_y + 40)

    # Position each node
    positions: Dict[str, Tuple[float, float]] = {}
    for idx, node in enumerate(spec.nodes):
        c = idx % cols
        r = idx // cols
        # Center rows that have fewer columns
        row_items = min(cols, num_nodes - r * cols)
        row_offset = (actual_w - (row_items * (node_w + pad_x) - pad_x)) / 2
        x = row_offset + c * (node_w + pad_x)
        y = 50 + r * (node_h + pad_y)
        positions[node.id] = (x, y)

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {actual_w} {actual_h}" '
        f'width="100%" height="{actual_h}px" style="background:#090d16; border-radius:12px; font-family:system-ui,-apple-system,sans-serif;">',
        '  <defs>',
        '    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />',
        '    </marker>',
        '    <filter id="shadow" x="-5%" y="-5%" width="115%" height="115%">',
        '      <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#000" flood-opacity="0.4" />',
        '    </filter>',
        '  </defs>',
        f'  <text x="{actual_w/2}" y="28" fill="#94a3b8" font-size="12" font-weight="600" text-anchor="middle" letter-spacing="1">{spec.title.upper()}</text>',
    ]

    # Draw edges first so they sit below nodes
    for edge in spec.edges:
        if edge.source in positions and edge.target in positions:
            sx, sy = positions[edge.source]
            tx, ty = positions[edge.target]
            # Center of source to center of target
            start_x = sx + node_w / 2
            start_y = sy + node_h
            end_x = tx + node_w / 2
            end_y = ty

            # If same row, connect right-to-left
            if abs(sy - ty) < 10:
                start_x = sx + node_w
                start_y = sy + node_h / 2
                end_x = tx
                end_y = ty + node_h / 2
                path_d = f"M {start_x} {start_y} L {end_x} {end_y}"
            else:
                mid_y = (start_y + end_y) / 2
                path_d = f"M {start_x} {start_y} C {start_x} {mid_y}, {end_x} {mid_y}, {end_x} {end_y}"

            svg_lines.append(f'  <path d="{path_d}" fill="none" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />')
            if edge.label:
                mx = (start_x + end_x) / 2
                my = (start_y + end_y) / 2 - 4
                svg_lines.append(f'  <text x="{mx}" y="{my}" fill="#94a3b8" font-size="10" font-weight="500" text-anchor="middle">{edge.label}</text>')

    # Draw nodes
    for node in spec.nodes:
        x, y = positions.get(node.id, (0, 0))
        palette = KIND_COLORS.get(node.kind, KIND_COLORS["generic"])
        hex_stroke = palette["hex_stroke"]
        hex_bg = palette["hex_bg"]
        hex_fill = palette["hex_fill"]

        svg_lines.append(f'  <g filter="url(#shadow)">')
        svg_lines.append(f'    <rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="8" fill="{hex_bg}" stroke="{hex_stroke}" stroke-width="1.5" />')
        svg_lines.append(f'    <rect x="{x+6}" y="{y+6}" width="4" height="{node_h-12}" rx="2" fill="{hex_fill}" />')
        # Labels
        clean_lbl = node.label[:22]
        clean_sub = (node.sublabel or "")[:24]
        if clean_sub:
            svg_lines.append(f'    <text x="{x+18}" y="{y+26}" fill="#f8fafc" font-size="12" font-weight="700">{clean_lbl}</text>')
            svg_lines.append(f'    <text x="{x+18}" y="{y+44}" fill="#94a3b8" font-size="10">{clean_sub}</text>')
        else:
            svg_lines.append(f'    <text x="{x+18}" y="{y+35}" fill="#f8fafc" font-size="13" font-weight="700">{clean_lbl}</text>')
        svg_lines.append('  </g>')

    svg_lines.append('</svg>')
    return "\n".join(svg_lines)


def render_png(spec: DiagramSpec, width: int = 800) -> bytes:
    """
    Renders DiagramSpec to a high-resolution PNG image byte buffer using Pillow.
    Provides deterministic raster diagrams for ReportLab PDF embedding.
    """
    num_nodes = len(spec.nodes)
    if num_nodes == 0:
        img = Image.new("RGB", (width, 80), color=(15, 23, 42))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    node_w = 170
    node_h = 60
    pad_x = 40
    pad_y = 60

    cols = min(3, max(1, num_nodes))
    rows = math.ceil(num_nodes / cols)

    actual_w = max(width, cols * (node_w + pad_x) + pad_x)
    actual_h = rows * (node_h + pad_y) + pad_y + 40

    img = Image.new("RGB", (actual_w, actual_h), color=(9, 13, 22))
    draw = ImageDraw.Draw(img)

    # Title
    title_text = spec.title.upper()
    draw.text((actual_w // 2 - len(title_text) * 3, 16), title_text, fill=(148, 163, 184))

    positions: Dict[str, Tuple[int, int]] = {}
    for idx, node in enumerate(spec.nodes):
        c = idx % cols
        r = idx // cols
        row_items = min(cols, num_nodes - r * cols)
        row_offset = (actual_w - (row_items * (node_w + pad_x) - pad_x)) // 2
        x = int(row_offset + c * (node_w + pad_x))
        y = int(50 + r * (node_h + pad_y))
        positions[node.id] = (x, y)

    # Draw edges
    for edge in spec.edges:
        if edge.source in positions and edge.target in positions:
            sx, sy = positions[edge.source]
            tx, ty = positions[edge.target]
            if abs(sy - ty) < 10:
                p1 = (sx + node_w, sy + node_h // 2)
                p2 = (tx, ty + node_h // 2)
            else:
                p1 = (sx + node_w // 2, sy + node_h)
                p2 = (tx + node_w // 2, ty)
            draw.line([p1, p2], fill=(71, 85, 105), width=2)
            # Arrow head
            draw.polygon([
                (p2[0], p2[1]),
                (p2[0] - 5, p2[1] - 8),
                (p2[0] + 5, p2[1] - 8),
            ], fill=(100, 116, 139))
            if edge.label:
                mid = ((p1[0] + p2[0]) // 2 - len(edge.label) * 3, (p1[1] + p2[1]) // 2 - 10)
                draw.text(mid, edge.label, fill=(148, 163, 184))

    # Draw nodes
    for node in spec.nodes:
        x, y = positions[node.id]
        palette = KIND_COLORS.get(node.kind, KIND_COLORS["generic"])
        # Node box
        draw.rounded_rectangle(
            [x, y, x + node_w, y + node_h],
            radius=8,
            fill=(24, 30, 42),
            outline=palette["stroke"],
            width=2,
        )
        # Accent indicator
        draw.rounded_rectangle(
            [x + 6, y + 6, x + 10, y + node_h - 6],
            radius=2,
            fill=palette["fill"],
        )
        # Text
        lbl = node.label[:22]
        sub = (node.sublabel or "")[:24]
        draw.text((x + 18, y + 14), lbl, fill=(248, 250, 252))
        if sub:
            draw.text((x + 18, y + 34), sub, fill=(148, 163, 184))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
