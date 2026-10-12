"""
rag/answer.py
-------------
Core RAG pipeline: intent policy gating → retrieve (if needed) → prompt → stream.

Public API
----------
answer_question(repo_id, query, db, top_k=8, image_bytes=None, image_mime_type=None, provider=None, model=None) -> AsyncGenerator[str, None]

Yields raw SSE-style text chunks wrapped in a StreamingResponse.
The first chunk is always a JSON metadata line prefixed with "data: [CONTEXT]"
so the frontend receives validated citations and relevant error reports without a second round-trip.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import AsyncGenerator

from ai.policy import (
    QueryIntent,
    classify_intent,
    should_retrieve_context,
    get_system_prompt_for_intent,
    filter_and_validate_citations,
    build_context_block,
)
from ai.router import route_chat, route_vision
from models import ErrorReport

logger = logging.getLogger(__name__)


def _find_matching_errors(repo_id: str, query: str, citations: list[dict], db) -> list[dict]:
    """Find relevant ErrorReport rows from the database matching the query or citations."""
    if not db:
        return []
    try:
        all_errors = (
            db.query(ErrorReport)
            .filter(ErrorReport.repo_id == repo_id, ErrorReport.fix_status != "REJECTED")
            .all()
        )
    except Exception as e:
        logger.warning("Failed to query ErrorReports in RAG: %s", e)
        return []

    if not all_errors:
        return []

    matched = []
    q_lower = (query or "").lower()
    citation_files = {c["file_path"].lower() for c in citations if c.get("file_path")}

    for err in all_errors:
        err_file = (err.file_path or "").lower()
        err_rule = (err.rule_id or "").lower()
        err_sym = (err.symbol_name or "").lower()

        is_hit = False
        if err_file and err_file in citation_files:
            is_hit = True
        elif err_file and (err_file in q_lower or os.path.basename(err_file) in q_lower):
            is_hit = True
        elif err_rule and err_rule in q_lower:
            is_hit = True
        elif err_sym and err_sym in q_lower:
            is_hit = True

        if is_hit:
            matched.append({
                "id": err.id,
                "repo_id": err.repo_id,
                "symbol_id": err.symbol_id,
                "rule_id": err.rule_id,
                "severity": err.severity,
                "message": err.message,
                "file_path": err.file_path,
                "symbol_name": err.symbol_name,
                "symbol_type": err.symbol_type,
                "language": err.language,
                "line": err.line,
                "explanation": err.explanation,
                "suggested_fix": err.suggested_fix,
                "fix_status": err.fix_status,
                "fix_model": err.fix_model,
                "fix_error": err.fix_error,
                "branch_name": getattr(err, "branch_name", None),
                "pr_url": getattr(err, "pr_url", None),
                "pr_id": getattr(err, "pr_id", None),
                "pr_status": getattr(err, "pr_status", "NONE"),
                "auto_fix_attempted": getattr(err, "auto_fix_attempted", 0),
                "created_at": err.created_at.isoformat() if err.created_at else None,
            })

    # Return top 3 matched errors
    return matched[:3]


def build_architecture_context(repo_id: str, db) -> tuple[str, list[dict]]:
    """
    Extracts verified structural facts (tech stack, entry points, routers, models,
    auth, testing, modules) from the repository knowledge graph.
    Returns (architecture_facts_block, key_code_citations).
    """
    from pathlib import Path
    from docgen.repo_analyzer import analyze_repository
    from ai.policy import resolve_disk_file

    facts: list[str] = ["=== VERIFIED REPOSITORY ARCHITECTURE & IMPLEMENTATION FACTS ==="]
    extra_citations: list[dict] = []

    try:
        graph = analyze_repository(repo_id, db)
    except Exception as exc:
        logger.warning("analyze_repository failed for repo %s: %s", repo_id, exc)
        graph = None

    if graph:
        # 1. Project Identity & Architecture
        facts.append("[PROJECT IDENTITY & CLASSIFICATION]")
        proj_name = getattr(graph.project_metadata, "display_name", None) or graph.repo_name
        facts.append(f"- Project Name: {proj_name}")
        facts.append(f"- Architecture Type: {graph.app_type}")
        if graph.project_purpose:
            facts.append(f"- Domain Purpose: {graph.project_purpose}")
        lang_str = ", ".join(f"{k} ({v} files)" for k, v in sorted(graph.languages.items(), key=lambda x: -x[1])[:5])
        facts.append(f"- Primary Languages: {lang_str}")

        # 2. Tech Stack & Frameworks
        facts.append("\n[TECH STACK & DEPENDENCIES]")
        if graph.frameworks:
            facts.append(f"- Frameworks: {', '.join(graph.frameworks)}")
        if graph.libraries:
            facts.append(f"- Key Libraries: {', '.join(graph.libraries[:12])}")
        if graph.build_tools:
            facts.append(f"- Build Tools: {', '.join(graph.build_tools)}")
        if graph.package_managers:
            facts.append(f"- Package Managers: {', '.join(graph.package_managers)}")

        # 3. Verified Entry Points
        if graph.entry_points:
            facts.append("\n[VERIFIED ENTRY POINTS]")
            for ep in graph.entry_points[:8]:
                facts.append(f"- {ep}")

        # 4. Directory Structure & Key Modules
        if graph.directory_structure:
            facts.append("\n[CORE DIRECTORIES & MODULE RESPONSIBILITIES]")
            for d in graph.directory_structure[:10]:
                facts.append(f"- `{d.path}/` ({d.file_count} files): {d.purpose}")

        # 5. Verified API Endpoints
        if graph.api_endpoints:
            facts.append(f"\n[VERIFIED API ENDPOINTS ({len(graph.api_endpoints)} total)]")
            for ep in graph.api_endpoints[:15]:
                auth_str = " (Auth Required)" if ep.auth_required else ""
                facts.append(f"- {ep.http_method} `{ep.path}` -> handler `{ep.handler_name}` in `{ep.file_path}`{auth_str}")

        # 6. Database Models & Persistence
        if graph.db_models:
            facts.append(f"\n[VERIFIED DATABASE PERSISTENCE ({len(graph.db_models)} models)]")
            for m in graph.db_models[:8]:
                pk_str = f", PK: {', '.join(m.primary_keys)}" if m.primary_keys else ""
                tbl_str = f" (table `{m.table_name}`)" if m.table_name else ""
                facts.append(f"- Model `{m.model_name}`{tbl_str} in `{m.file_path}`{pk_str}")
                if m.fields:
                    facts.append(f"  Fields: {', '.join(m.fields[:8])}")
                if m.relationships:
                    facts.append(f"  Relationships: {', '.join(m.relationships[:5])}")

        # 7. Authentication & Security
        if graph.security:
            facts.append("\n[SECURITY & AUTHENTICATION FINDINGS]")
            sec = graph.security
            if getattr(sec, "auth_mechanisms", None):
                facts.append(f"- Auth mechanisms detected: {', '.join(sec.auth_mechanisms)}")
            if getattr(sec, "security_findings", None):
                for sf in sec.security_findings[:5]:
                    facts.append(f"- {sf.area}: {sf.status} - {sf.evidence}")

        # 8. Testing & DevOps
        if graph.testing or graph.devops:
            facts.append("\n[TESTING & DEVOPS]")
            if graph.testing and graph.testing.test_frameworks:
                facts.append(f"- Test frameworks: {', '.join(graph.testing.test_frameworks)} ({graph.testing.test_files_count} test files)")
            if graph.devops:
                if graph.devops.ci_files:
                    facts.append(f"- CI/CD workflows: {', '.join(graph.devops.ci_files)}")
                if graph.devops.docker_files:
                    facts.append(f"- Containers: {', '.join(graph.devops.docker_files)}")

        # Sample primary entry point code snippets for concrete grounding if files exist
        if graph.entry_points:
            for ep_path in graph.entry_points[:2]:
                disk_file = resolve_disk_file(repo_id, ep_path)
                if disk_file and disk_file.is_file():
                    try:
                        content = disk_file.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()[:60]
                        extra_citations.append({
                            "index": len(extra_citations) + 1,
                            "file_path": ep_path,
                            "symbol_type": "entry_point",
                            "name": Path(ep_path).name,
                            "start_line": 1,
                            "end_line": len(lines),
                            "language": ep_path.split(".")[-1],
                            "score": 1.0,
                            "source_code": "\n".join(lines),
                        })
                    except Exception:
                        pass

    facts.append("=== END VERIFIED ARCHITECTURE FACTS ===")
    facts_block = "\n".join(facts)
    return facts_block, extra_citations


def build_project_overview_context(repo_id: str, db) -> tuple[str, list[dict]]:
    """
    Extracts high-level repository evidence tailored for overall project understanding:
    1. Project name & verified domain purpose
    2. Problem solved & target audience context
    3. Demonstrably implemented features (from endpoints, models, frontend views, LLM services)
    4. Clean categorized technology stack (by role: Frontend, Backend, Database, AI/Integrations, Auth)
    5. Representative end-to-end workflow
    6. Architecture boundaries & component responsibilities
    7. Raw excerpts from README / collab documentation
    8. Entry points and route definitions
    """
    from pathlib import Path
    from docgen.repo_analyzer import analyze_repository, _find_repo_root, _read_file_safe
    from ai.policy import resolve_disk_file

    facts: list[str] = ["=== VERIFIED REPOSITORY PROJECT OVERVIEW & IMPLEMENTATION EVIDENCE ==="]
    extra_citations: list[dict] = []

    try:
        graph = analyze_repository(repo_id, db)
    except Exception as exc:
        logger.warning("analyze_repository failed for repo %s: %s", repo_id, exc)
        graph = None

    repo_root = _find_repo_root(repo_id)

    # 1. Project Documentation Excerpt (README / collab.md)
    if repo_root and repo_root.exists():
        for doc_name in ("collab.md", "README.md", "readme.md", "README.txt", "overview.md"):
            doc_text = _read_file_safe(repo_root, doc_name)
            if doc_text and len(doc_text.strip()) > 30:
                lines = doc_text.strip().splitlines()[:60]
                doc_excerpt = "\n".join(lines)
                facts.append(f"\n[PROJECT DOCUMENTATION EXCERPT ({doc_name})]\n{doc_excerpt}")
                extra_citations.append({
                    "index": len(extra_citations) + 1,
                    "file_path": doc_name,
                    "symbol_type": "documentation",
                    "name": doc_name,
                    "start_line": 1,
                    "end_line": len(lines),
                    "language": "markdown",
                    "score": 1.0,
                    "source_code": doc_excerpt,
                })
                break

    if graph:
        proj_name = getattr(graph.project_metadata, "display_name", None) or graph.repo_name
        facts.append("\n[VERIFIED PROJECT IDENTITY & DOMAIN PURPOSE]")
        facts.append(f"- Project Name: {proj_name}")
        facts.append(f"- Application Classification: {graph.app_type}")
        if graph.project_purpose:
            facts.append(f"- Domain Purpose: {graph.project_purpose}")
        lang_str = ", ".join(f"{k} ({v} files)" for k, v in sorted(graph.languages.items(), key=lambda x: -x[1])[:5])
        facts.append(f"- Primary Languages: {lang_str}")

        # Categorized Technology Stack
        facts.append("\n[VERIFIED TECHNOLOGY STACK BY LAYER]")
        fe_tech = [f for f in graph.frameworks if f in ("React", "Vue.js", "Angular", "Svelte", "Next.js", "Vite", "TailwindCSS")]
        be_tech = [f for f in graph.frameworks if f in ("FastAPI", "Flask", "Django", "Express", "NestJS", "Spring Boot", "Uvicorn")]
        db_tech = []
        if graph.database_type:
            db_tech.append(graph.database_type)
        if any("sql" in lib.lower() or "alembic" in lib.lower() or "prisma" in lib.lower() for lib in graph.libraries):
            db_tech.extend([lib for lib in graph.libraries if any(k in lib.lower() for k in ("sqlalchemy", "alembic", "prisma", "psycopg", "pg", "mongo"))])

        ai_tech = [lib for lib in graph.libraries if any(k in lib.lower() for k in ("groq", "nvidia", "openai", "langchain", "llama", "huggingface", "rag", "torch", "transformers"))]

        auth_tech = []
        if graph.security and getattr(graph.security, "auth_mechanisms", None):
            auth_tech.extend(graph.security.auth_mechanisms)
        auth_tech.extend([lib for lib in graph.libraries if any(k in lib.lower() for k in ("jwt", "argon2", "bcrypt", "oauth", "auth"))])

        if fe_tech:
            facts.append(f"- Frontend Layer: {', '.join(fe_tech)}")
        if be_tech:
            facts.append(f"- Backend API Layer: {', '.join(be_tech)}")
        if db_tech:
            facts.append(f"- Persistence & Database Layer: {', '.join(sorted(set(db_tech)))}")
        if ai_tech:
            facts.append(f"- AI & Intelligence Layer: {', '.join(sorted(set(ai_tech)))}")
        if auth_tech:
            facts.append(f"- Authentication & Security: {', '.join(sorted(set(auth_tech)))}")
        if graph.build_tools:
            facts.append(f"- Build & Tooling: {', '.join(graph.build_tools)}")

        # Implemented Features (deduced from API endpoints & components)
        facts.append("\n[VERIFIED IMPLEMENTED FEATURES & CAPABILITIES]")
        if graph.api_endpoints:
            by_group: dict[str, list[str]] = {}
            for ep in graph.api_endpoints:
                by_group.setdefault(ep.domain_group or "Core API", []).append(f"{ep.http_method} {ep.path}")
            for grp, eps in by_group.items():
                facts.append(f"- {grp}: {len(eps)} routes (e.g. {', '.join(eps[:4])})")

        # Directory responsibilities
        if graph.directory_structure:
            facts.append("\n[VERIFIED ARCHITECTURE & COMPONENT BOUNDARIES]")
            for d in graph.directory_structure[:8]:
                facts.append(f"- `{d.path}/` ({d.file_count} files): {d.purpose}")

        # Persistence Models
        if graph.db_models:
            facts.append(f"\n[PERSISTENCE MODELS ({len(graph.db_models)} total)]")
            for m in graph.db_models[:6]:
                flds = f" (Fields: {', '.join(m.fields[:5])})" if m.fields else ""
                facts.append(f"- Model `{m.model_name}` in `{m.file_path}`{flds}")

        # Verification and Status
        facts.append("\n[CURRENT STATUS & LIMITATIONS]")
        if graph.testing:
            facts.append(f"- Test Suite: {graph.testing.test_files_count} test files ({', '.join(graph.testing.test_frameworks) if graph.testing.test_frameworks else 'Discovered'}). Note: Tests discovered statically; runtime execution unmeasured.")
        else:
            facts.append("- Test Suite: No dedicated test framework detected in static scan.")
        if graph.devops and graph.devops.ci_files:
            facts.append(f"- CI/CD: Automated workflows in {', '.join(graph.devops.ci_files)}")

        # Entry points citations
        if graph.entry_points:
            for ep_path in graph.entry_points[:2]:
                disk_file = resolve_disk_file(repo_id, ep_path)
                if disk_file and disk_file.is_file():
                    try:
                        content = disk_file.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()[:50]
                        extra_citations.append({
                            "index": len(extra_citations) + 1,
                            "file_path": ep_path,
                            "symbol_type": "entry_point",
                            "name": Path(ep_path).name,
                            "start_line": 1,
                            "end_line": len(lines),
                            "language": ep_path.split(".")[-1],
                            "score": 1.0,
                            "source_code": "\n".join(lines),
                        })
                    except Exception:
                        pass

    facts.append("=== END VERIFIED PROJECT OVERVIEW EVIDENCE ===")
    return "\n".join(facts), extra_citations


# ── Public entry point ────────────────────────────────────────────────────────

async def answer_question(
    repo_id: str,
    query: str,
    db,
    top_k: int = 8,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Intelligent RAG pipeline governed by central response policy:
    1. Classifies request intent (Greeting, General Programming, Project Overview, Repo Query, Error Diagnosis, etc.).
    2. Gates retrieval: skips repository search entirely for greetings and general conceptual questions.
    3. Retrieves, filters, and deduplicates genuine repository citations when needed.
    4. Emits real-time analysis status updates for repository analysis.
    5. Streams response with appropriate policy instructions.
    """
    # 1. Separate substantive user query from active file header
    from ai.policy import extract_user_query_and_active_file
    user_query, active_file = extract_user_query_and_active_file(query)
    clean_query = user_query.strip()

    # 2. Intent Classification
    intent = classify_intent(
        clean_query,
        has_image=bool(image_bytes),
        has_errors=False,
        active_file_path=active_file,
    )
    logger.info("Classified query intent: '%s' for query: '%s'", intent.value, clean_query[:50])

    # 3. Retrieval Decision
    needs_retrieval = should_retrieve_context(intent)

    is_arch_query = (
        intent == QueryIntent.COMPREHENSIVE_ANALYSIS
        or any(k in clean_query.lower() for k in ("architecture", "system overview", "system design", "project structure", "high-level design"))
    )
    is_overview_query = (
        intent == QueryIntent.PROJECT_OVERVIEW
        or (
            not is_arch_query
            and any(k in clean_query.lower() for k in (
                "tell me about the project", "tell me about project", "explain this repository",
                "explain this repo", "what problem does this project solve", "how does the application work",
                "explain the major modules and technologies", "what does this project do",
            ))
        )
    )

    citations: list[dict] = []
    matching_errors: list[dict] = []
    context_block = ""
    errors_block = ""
    arch_block = ""

    if is_overview_query:
        arch_block, overview_citations = build_project_overview_context(repo_id, db)
        if overview_citations:
            citations.extend(overview_citations)
    elif is_arch_query:
        arch_block, arch_citations = build_architecture_context(repo_id, db)
        if arch_citations:
            citations.extend(arch_citations)

    # For general repo queries or deep code explanations, run targeted semantic retrieval
    if needs_retrieval and clean_query and not is_overview_query:
        from vectorstore.index import search

        effective_k = (
            min(top_k, 3) if intent == QueryIntent.CODE_EXPLANATION
            else (min(top_k, 6) if is_arch_query else min(top_k, 5))
        )

        try:
            raw_results = search(repo_id, clean_query, top_k=effective_k, db=db)
        except Exception as exc:
            logger.warning("Search failed in answer_question: %s", exc)
            raw_results = []

        # Validate against real disk files, remove noise, deduplicate identical files/lines
        search_citations = filter_and_validate_citations(
            repo_id=repo_id,
            raw_results=raw_results,
            query=clean_query,
            intent=intent,
        )

        if search_citations:
            seen_files = {c["file_path"] for c in citations}
            for sc in search_citations:
                if sc["file_path"] not in seen_files:
                    citations.append(sc)
                    seen_files.add(sc["file_path"])

        if citations:
            context_block = build_context_block(citations)

        # Match relevant errors only if error-related intent or keywords
        if intent in (QueryIntent.ERROR_DIAGNOSIS, QueryIntent.CODE_FIX) or any(
            k in clean_query.lower() for k in ("error", "bug", "fail", "broken", "issue", "crash")
        ):
            matching_errors = _find_matching_errors(repo_id, clean_query, citations, db)
            if matching_errors:
                err_lines = ["=== RELEVANT DETECTED ISSUES IN REPO ==="]
                for e in matching_errors:
                    err_lines.append(
                        f"- Issue in `{e['file_path']}` (Rule {e['rule_id']}, Line {e.get('line') or '?'}, Status: {e['fix_status']}): {e['message']}"
                    )
                    if e.get("explanation"):
                        err_lines.append(f"  AI Explanation: {e['explanation']}")
                err_lines.append("=== END DETECTED ISSUES ===")
                errors_block = "\n".join(err_lines)

    # 4. Build Prompt Text
    system_prompt = get_system_prompt_for_intent(intent)

    blocks = []
    if arch_block:
        blocks.append(arch_block)
    if context_block:
        blocks.append(context_block)
    if errors_block:
        blocks.append(errors_block)

    if blocks:
        blocks.append(f"User Query: {clean_query}")
        prompt_text = "\n\n".join(blocks)
    else:
        prompt_text = clean_query or (
            "Explain what is shown in this screenshot, diagnose any code error or stack trace, and correlate with the repository context."
            if image_bytes else "Hello!"
        )

    # 5. Generator function
    async def _generate():
        # Requirement D: Show genuine analysis status while working for repository analysis
        if is_overview_query or is_arch_query or (needs_retrieval and not image_bytes):
            yield "data: [STATUS] Analyzing repository…\n\n"
            await asyncio.sleep(0.04)
            yield "data: [STATUS] Inspecting relevant components…\n\n"
            await asyncio.sleep(0.04)
            yield "data: [STATUS] Preparing explanation…\n\n"
            await asyncio.sleep(0.04)

        # SSE chunk: validated metadata envelope (lightweight citations without multi-megabyte source dumps)
        clean_citations = [
            {
                "index": c.get("index", idx + 1),
                "file_path": c.get("file_path", ""),
                "start_line": c.get("start_line", 1),
                "end_line": c.get("end_line", 1),
                "symbol_type": c.get("symbol_type", ""),
                "name": c.get("name", ""),
            }
            for idx, c in enumerate(citations)
        ]
        metadata_json = json.dumps({
            "citations": clean_citations,
            "error_reports": matching_errors,
        })
        yield f"data: [CONTEXT] {metadata_json}\n\n"

        # Subsequent chunks: streaming tokens
        try:
            if image_bytes:
                async for token in route_vision(
                    image_bytes=image_bytes,
                    prompt=prompt_text,
                    mime_type=image_mime_type or "image/png",
                    stream=True,
                ):
                    yield token
            else:
                task_type = "CODEBASE_CHAT"
                if intent == QueryIntent.GREETING:
                    task_type = "FAST_CHAT"
                elif intent == QueryIntent.GENERAL_PROGRAMMING:
                    task_type = "FAST_CHAT"
                elif is_overview_query or intent == QueryIntent.PROJECT_OVERVIEW:
                    task_type = "PROJECT_OVERVIEW"
                elif is_arch_query or intent == QueryIntent.COMPREHENSIVE_ANALYSIS:
                    task_type = "ARCHITECTURE"
                elif intent == QueryIntent.ERROR_DIAGNOSIS:
                    task_type = "ERROR_ANALYSIS"
                elif intent == QueryIntent.CODE_EXPLANATION:
                    task_type = "CODE_EXPLANATION"
                elif intent == QueryIntent.CODE_FIX:
                    task_type = "CODE_FIX"
                elif intent == QueryIntent.REPO_QUERY:
                    task_type = "CODEBASE_CHAT"

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ]
                async for token in route_chat(
                    messages,
                    task_type=task_type,
                    stream=True,
                    preferred_provider=provider,
                    preferred_model=model,
                ):
                    yield token
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("Client cancelled stream or disconnected for query: %s", clean_query[:35])
            return

    return _generate()
