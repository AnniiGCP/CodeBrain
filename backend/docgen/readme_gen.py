"""
docgen/readme_gen.py
--------------------
Generate a README.md for an entire repository.

Public API
----------
generate_repo_readme(repo_id, db) -> str   (complete markdown string)
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from pathlib import Path
import re

logger = logging.getLogger(__name__)


def sanitize_readme_text(text: str) -> str:
    """
    Sanitize generated README text by removing AI conversational preambles,
    unwanted XML/document artifact tags (e.g. <WritingBlock>), and markdown fences.
    """
    if not text:
        return ""
    cleaned = text.strip()
    # 1. Strip artifact tags like <WritingBlock ...> or </WritingBlock>
    cleaned = re.sub(r"<\/?(?:WritingBlock|artifact|document|thought|antArtifact)[^>]*>", "", cleaned, flags=re.IGNORECASE)

    # 2. Strip conversational preambles before the first markdown heading (# ...)
    first_heading = re.search(r"(?m)^#\s+[^\n]+", cleaned)
    if first_heading and first_heading.start() > 0:
        preamble = cleaned[:first_heading.start()].strip()
        conversational_markers = [
            "below is",
            "here is",
            "sure",
            "i have created",
            "based strictly",
            "written for",
            "documents the",
            "as requested",
        ]
        if any(marker in preamble.lower() for marker in conversational_markers):
            cleaned = cleaned[first_heading.start():].strip()

    # 3. If wrapped in outer code fences ```markdown ... ```, unwrap it
    fence_match = re.match(r"^\s*```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    return cleaned.strip()

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a senior software engineer writing developer documentation.
Your task is to produce a high-quality README.md for the repository described below.

Requirements:
- Write ONLY what is supported by the provided code context.
- Do NOT invent features, endpoints, or dependencies that are not visible in the code.
- Structure: Title, Badges row (language badges only), Overview, Project Structure,
  Key Modules (one subsection per main file/module), Setup & Installation,
  Usage Examples (derived from the code — not invented), and Contributing.
- Use GitHub-flavoured Markdown.
- Code blocks must use fenced syntax with the correct language tag.
- Keep each section concise. Prefer bullet points over prose walls.
"""

_USER_TEMPLATE = """\
## Repository: {repo_name}

### File tree
```
{file_tree_text}
```

### Detected languages
{languages_text}

### Key symbols (functions, classes, modules)
{symbols_text}

Now write the complete README.md for this repository.
"""

# ── Context builders ──────────────────────────────────────────────────────────

_MAX_SYMBOLS = 40          # cap to stay within token limit
_MAX_SOURCE_LINES = 25     # max lines per symbol in the context


def _build_file_tree_text(files: list) -> str:
    """Render a simple indented file tree from RepoFile rows."""
    lines: list[str] = []
    for rf in sorted(files, key=lambda f: f.path):
        depth = rf.path.count("/")
        indent = "  " * depth
        name = rf.path.split("/")[-1]
        lines.append(f"{indent}{name}")
    return "\n".join(lines) if lines else "(no files)"


def _build_languages_text(files: list) -> str:
    counts: Counter[str] = Counter()
    for rf in files:
        lang = rf.language or "unknown"
        counts[lang] += 1
    parts = [f"{lang}: {n} file{'s' if n > 1 else ''}" for lang, n in counts.most_common()]
    return "\n".join(f"- {p}" for p in parts)


def _truncate_source(source: str, max_lines: int) -> str:
    lines = source.splitlines()
    if len(lines) <= max_lines:
        return source
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def _build_symbols_text(db, repo_id: str) -> str:
    from models import Symbol, RepoFile

    # Prefer top-level functions/classes (not methods); limit total
    symbols = (
        db.query(Symbol)
        .filter(Symbol.repo_id == repo_id)
        .order_by(Symbol.symbol_type)
        .limit(_MAX_SYMBOLS * 3)  # fetch extra, then filter
        .all()
    )

    # Group by file for context
    by_file: dict[str, list] = defaultdict(list)
    for sym in symbols:
        rf = db.query(RepoFile).filter(RepoFile.id == sym.file_id).first()
        path = rf.path if rf else "unknown"
        by_file[path].append(sym)

    parts: list[str] = []
    total = 0
    for path, syms in by_file.items():
        for sym in syms:
            if total >= _MAX_SYMBOLS:
                break
            source_snippet = _truncate_source(sym.source_code, _MAX_SOURCE_LINES)
            parts.append(
                f"### [{sym.symbol_type}] `{sym.name}` in `{path}`\n"
                f"```\n{source_snippet}\n```"
            )
            total += 1

    return "\n\n".join(parts) if parts else "(no symbols extracted yet — embed the repo first)"


# ── Public function ────────────────────────────────────────────────────────────

def generate_repo_readme(repo_id: str, db, graph=None) -> str:
    """
    Gather repo context and generate a complete, professional, project-specific README.md.
    Uses LLM synthesis when available and falls back to a deterministic evidence-grounded builder.
    """
    from models import Repo, RepoFile
    from docgen.groq_client import call_groq
    from docgen.secret_redactor import redact_secrets

    repo = db.query(Repo).filter(Repo.id == repo_id).first()
    if not repo:
        raise ValueError(f"Repo {repo_id!r} not found")

    files = db.query(RepoFile).filter(RepoFile.repo_id == repo_id).order_by(RepoFile.path).all()

    # If graph is not passed, analyze repository if possible
    if graph is None:
        try:
            from docgen.repo_analyzer import analyze_repository
            graph = analyze_repository(repo_id, db)
        except Exception:
            graph = None

    project_name = (graph.project_metadata.project_name if graph and graph.project_metadata else repo.name) or repo.name
    file_tree_text = _build_file_tree_text(files)
    languages_text = _build_languages_text(files)
    symbols_text = _build_symbols_text(db, repo_id)

    # Compile structured evidence from graph if available
    purpose = graph.project_purpose if graph else "Software application repository."
    app_type = graph.app_type if graph else "General Software"
    tech_stack_items = []
    if graph:
        for lang in graph.languages:
            tech_stack_items.append(f"- **Language:** {lang}")
        for fw in graph.frameworks:
            tech_stack_items.append(f"- **Framework:** {fw}")
        for pm in graph.package_managers:
            tech_stack_items.append(f"- **Package Manager:** {pm}")
        if getattr(graph, "database_type", None):
            tech_stack_items.append(f"- **Database:** {graph.database_type}")
    tech_summary = "\n".join(tech_stack_items) if tech_stack_items else languages_text

    apis_summary = ""
    if graph and graph.api_endpoints:
        apis_summary = "\n".join([f"- `{a.http_method}` `{a.path}` ({a.handler_name})" for a in graph.api_endpoints[:15]])

    db_summary = ""
    if graph and graph.db_models:
        db_summary = "\n".join([f"- **`{m.model_name}`**: fields `({', '.join(m.fields[:4])})`" for m in graph.db_models[:10]])

    tests_summary = ""
    if graph and graph.testing.test_files_count > 0:
        tests_summary = f"Frameworks: {', '.join(graph.testing.test_frameworks) or 'Native'}\nCommands: {', '.join(graph.testing.test_commands) or 'Standard runner'}\nFiles: {graph.testing.test_files_count} test files"

    env_vars_summary = ""
    if graph and graph.security.config_vars:
        env_vars_summary = "\n".join([f"- `{v}`" for v in graph.security.config_vars[:15]])

    setup_summary = ""
    if graph and getattr(graph, "setup_commands", []):
        setup_summary = "\n".join([f"{i+1}. `{c}`" for i, c in enumerate(graph.setup_commands)])
    else:
        setup_summary = "1. Clone repository\n2. Install package dependencies\n3. Execute primary entry point"

    system_instruction = (
        "You are an executive software technical writer generating a professional, publication-grade README.md for a software repository.\n"
        "CRITICAL RULES:\n"
        f"1. Document ONLY the project named '{project_name}'.\n"
        "2. Ground all claims strictly in provided repository evidence. NEVER invent features, external databases, or third-party platforms.\n"
        "3. Include these standard sections:\n"
        "   - Project Title & High-level Description\n"
        "   - Problem Statement & Purpose\n"
        "   - Key Features\n"
        "   - Technology Stack\n"
        "   - Architecture Overview\n"
        "   - Repository Structure\n"
        "   - Installation & Local Setup\n"
        "   - Environment Variables (if evidence exists)\n"
        "   - Running Locally\n"
        "   - Testing (if test evidence exists)\n"
        "   - API Overview (if endpoints detected)\n"
        "   - Database Overview (if persistent models detected)\n"
        "   - Deployment & CI/CD (if DevOps configs detected)\n"
        "   - Usage & Important Notes\n"
        "4. Never output model names, provider disclaimers, or internal tool traces.\n"
        "5. Format cleanly using GitHub Flavored Markdown."
    )

    user_msg = f"""## Repository: {project_name}
Type: {app_type}
Purpose: {purpose}

### Verified Technology Stack:
{tech_summary}

### Repository File Structure:
```text
{file_tree_text[:1500]}
```

### Verified API Endpoints:
{apis_summary or 'None detected'}

### Verified Database Schema:
{db_summary or 'None detected'}

### Setup & Commands:
{setup_summary}

### Environment Variables:
{env_vars_summary or 'None detected'}

### Testing:
{tests_summary or 'None detected'}

### Key Symbols:
{symbols_text[:2000]}

Write the complete project-specific README.md for {project_name} based strictly on this evidence.
"""

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_msg},
    ]

    logger.info("Generating professional README for repo %s (%d files)", repo_id, len(files))
    try:
        raw_readme = call_groq(messages, max_tokens=3500, temperature=0.15)
        clean_readme = sanitize_readme_text(redact_secrets(raw_readme))
        if clean_readme and len(clean_readme) > 200:
            return clean_readme
    except Exception as exc:
        logger.warning("LLM call for README failed (%s). Falling back to structured generator.", exc)

    # Deterministic fallback guaranteed to succeed without external dependencies
    tree_snippet = file_tree_text[:1200]
    api_section = f"\n## API Overview\n\n{apis_summary}\n" if apis_summary else ""
    db_section = f"\n## Database & Persistence\n\n{db_summary}\n" if db_summary else ""
    env_section = f"\n## Environment Variables\n\n{env_vars_summary}\n" if env_vars_summary else ""
    test_section = f"\n## Testing\n\n{tests_summary}\n" if tests_summary else ""

    raw_readme = f"""# {project_name}

> **{app_type}** — Technical Overview & Developer Guide  
> Generated from Verified Repository Evidence

## Description & Purpose
{purpose}

## Key Capabilities
- Architecture topology: **{app_type}**
- Analyzed codebase size: **{len(files)}** source files

## Technology Stack
{tech_summary}

## Repository Structure
```text
{tree_snippet}
```

## Installation & Getting Started
{setup_summary}
{env_section}{api_section}{db_section}{test_section}
## Usage & Key Modules
{symbols_text[:2000]}

## Important Notes
- All sensitive tokens, secrets, and private keys have been strictly redacted.
- Documentation compiled directly from static AST parsing and repository manifests.
"""
    return redact_secrets(raw_readme).strip()


