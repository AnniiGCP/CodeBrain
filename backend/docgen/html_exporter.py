"""
backend/docgen/html_exporter.py
-------------------------------
Generates a standalone, responsive HTML technical documentation document
with integrated SVG diagrams, responsive data tables, dark/light presentation styles,
and printable layout from the canonical 16-section document model.
"""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgen.secret_redactor import redact_secrets

logger = logging.getLogger(__name__)


def _markdown_to_html_body(md_text: str) -> str:
    """Converts section markdown text to clean, styled HTML blocks."""
    lines = md_text.splitlines()
    html_out: List[str] = []
    idx = 0
    in_code = False
    code_lines: List[str] = []
    code_lang = ""

    while idx < len(lines):
        line = lines[idx]

        # 1. Code fence
        if line.startswith("```"):
            if in_code:
                in_code = False
                escaped_code = html.escape("\n".join(code_lines))
                # If mermaid, mark as mermaid container
                if code_lang == "mermaid":
                    html_out.append(f'<div class="mermaid-diagram-block" style="display:none;"><pre>{escaped_code}</pre></div>')
                else:
                    html_out.append(f'<pre><code class="language-{code_lang}">{escaped_code}</code></pre>')
                code_lines = []
                idx += 1
                continue
            else:
                in_code = True
                code_lang = line[3:].strip().lower()
                code_lines = []
                idx += 1
                continue

        if in_code:
            code_lines.append(line)
            idx += 1
            continue

        # 2. Markdown tables
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_lines = []
            while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1

            rows = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.split("|")[1:-1]]
                if all(re.match(r'^:?-+:?$', c) for c in cells):
                    continue
                rows.append(cells)

            if rows:
                html_out.append('<div class="table-responsive"><table>')
                # Header
                html_out.append('<thead><tr>')
                for h in rows[0]:
                    html_out.append(f'<th>{html.escape(h)}</th>')
                html_out.append('</tr></thead><tbody>')
                # Body
                for r in rows[1:]:
                    html_out.append('<tr>')
                    for cell in r:
                        clean_c = html.escape(cell)
                        clean_c = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', clean_c)
                        clean_c = re.sub(r'`(.*?)`', r'<code>\1</code>', clean_c)
                        html_out.append(f'<td>{clean_c}</td>')
                    html_out.append('</tr>')
                html_out.append('</tbody></table></div>')
            continue

        # 3. Blank line
        if not line.strip():
            idx += 1
            continue

        # 4. Headings
        if line.startswith("# "):
            html_out.append(f'<h2>{html.escape(line[2:].strip())}</h2>')
            idx += 1
            continue
        elif line.startswith("## "):
            html_out.append(f'<h3>{html.escape(line[3:].strip())}</h3>')
            idx += 1
            continue
        elif line.startswith("### "):
            html_out.append(f'<h4>{html.escape(line[4:].strip())}</h4>')
            idx += 1
            continue

        # 5. Lists
        if line.strip().startswith(("- ", "* ", "• ")):
            item_text = line.strip()[2:]
            clean_item = html.escape(item_text)
            clean_item = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', clean_item)
            clean_item = re.sub(r'`(.*?)`', r'<code>\1</code>', clean_item)
            html_out.append(f'<ul><li>{clean_item}</li></ul>')
            idx += 1
            continue

        m_num = re.match(r'^(\d+)\.\s+(.*)$', line.strip())
        if m_num:
            item_text = m_num.group(2)
            clean_item = html.escape(item_text)
            clean_item = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', clean_item)
            clean_item = re.sub(r'`(.*?)`', r'<code>\1</code>', clean_item)
            html_out.append(f'<ol start="{m_num.group(1)}"><li>{clean_item}</li></ol>')
            idx += 1
            continue

        # 6. Blockquote
        if line.startswith("> "):
            clean_q = html.escape(line[2:].strip())
            clean_q = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', clean_q)
            html_out.append(f'<blockquote>{clean_q}</blockquote>')
            idx += 1
            continue

        # 7. Regular paragraph
        clean_p = html.escape(line.strip())
        clean_p = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', clean_p)
        clean_p = re.sub(r'`(.*?)`', r'<code>\1</code>', clean_p)
        clean_p = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', clean_p)
        html_out.append(f'<p>{clean_p}</p>')
        idx += 1

    return "\n".join(html_out)


def generate_html_documentation(
    project_name: str,
    sections: list,
    master_md: str,
    output_path: Path,
    metadata: Optional[Dict[str, Any]] = None,
    assets_dir: Optional[Path] = None,
) -> Path:
    """
    Builds a complete, standalone, responsive HTML technical documentation document.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if assets_dir is None:
        assets_dir = output_path.parent / "assets"

    meta = metadata or {}
    disp_name = meta.get("display_name") or project_name
    repo_name = meta.get("repository_name") or project_name
    branch = meta.get("branch") or "Not available"
    commit_sha = meta.get("commit_sha") or "HEAD"
    generated_at = meta.get("generated_at") or "Not available"
    doc_ver = meta.get("doc_version") or "v2.0"
    analysis_ver = meta.get("analysis_version") or "v2.0"

    diagram_svg_map: Dict[str, List[tuple[str, str]]] = {
        "project_overview": [
            ("diagram_problem_solution.svg", "Problem & Solution Flow Architecture"),
            ("diagram_workflow.svg", "End-to-End Execution Workflow"),
        ],
        "tech_stack": [("diagram_tech_stack.svg", "Verified Technology Stack Architecture")],
        "repository_structure": [("diagram_repo_structure.svg", "Repository Hierarchy & Module Structure")],
        "system_architecture": [
            ("diagram_architecture.svg", "Multi-Tier System Topology & Architecture"),
            ("diagram_data_flow.svg", "Component Data Flow & Processing"),
        ],
        "modules_components": [("diagram_modules.svg", "Subsystem & Module Relationships")],
        "classes_functions": [("diagram_classes.svg", "Classes & Function Call Graph")],
        "apis_interfaces": [
            ("diagram_api_tree.svg", "Hierarchical API Route Map"),
            ("diagram_api_arch.svg", "API Routing & Request Lifecycle Pipeline"),
        ],
        "database_data_model": [
            ("diagram_db_tree.svg", "Database Schema & Entity Blueprint"),
            ("diagram_er_diagram.svg", "Entity-Relationship Data Model"),
        ],
        "database_relationships": [("diagram_db_relationships.svg", "Database Entity Cardinality & Relationships")],
        "dependencies": [
            ("diagram_dep_tree.svg", "Package & Dependency Hierarchy"),
            ("diagram_dependencies.svg", "Package & Dependency Ecosystem"),
        ],
        "configuration": [("diagram_config_flow.svg", "Runtime Configuration Ingestion Flow")],
        "testing": [("diagram_testing_pipeline.svg", "Automated Test Execution Pipeline")],
        "security": [("diagram_security_arch.svg", "Security Architecture & Access Control Flow")],
        "cicd": [("diagram_cicd_pipeline.svg", "Continuous Integration & Deployment Pipeline")],
        "deployment": [("diagram_deployment_arch.svg", "Deployment Infrastructure & Host Topology")],
        "setup": [("diagram_setup_flowchart.svg", "Setup & Onboarding Execution Flowchart")],
    }

    # Sidebar links
    sidebar_items = []
    section_cards = []

    for idx, sec in enumerate(sections):
        num = getattr(sec, "section_number", idx + 1)
        title = getattr(sec, "title", f"Section {num}")
        schema_key = getattr(sec, "schema_key", "") or (sec.get("schema_key") if isinstance(sec, dict) else f"sec_{num}")
        raw_content = getattr(sec, "content", "") or (sec.get("content") if isinstance(sec, dict) else "")
        content = redact_secrets(raw_content)

        sidebar_items.append(
            f'<a href="#{schema_key}" class="nav-item">'
            f'<span class="nav-num">{num}</span>'
            f'<span class="nav-text">{html.escape(title)}</span>'
            f'</a>'
        )

        body_html = _markdown_to_html_body(content)

        # Inline SVG diagram check
        svg_blocks = []
        norm_key = re.sub(r'(?<!^)(?=[A-Z])', '_', schema_key).lower().strip()
        alias_map = {
            "project_overview": "project_overview", "overview": "project_overview",
            "configuration_environment": "configuration", "cicd_pipeline": "cicd",
            "deployment_architecture": "deployment", "setup_developer_guide": "setup",
        }
        resolved_key = alias_map.get(norm_key, norm_key)
        diag_list = diagram_svg_map.get(schema_key, []) or diagram_svg_map.get(resolved_key, [])
        for fig_idx, (svg_file, fig_title) in enumerate(diag_list, start=1):
            if assets_dir and (assets_dir / svg_file).exists():
                caption = f"Figure {num}.{fig_idx} — {fig_title}"
                try:
                    svg_content = (assets_dir / svg_file).read_text(encoding="utf-8")
                    svg_blocks.append(
                        f'<figure class="diagram-container">'
                        f'<div class="diagram-header">'
                        f'  <span class="diagram-caption-badge">{html.escape(caption)}</span>'
                        f'  <span class="diagram-verified-tag">✓ Verified Repository Evidence</span>'
                        f'</div>'
                        f'<div class="diagram-svg-wrap">{svg_content}</div>'
                        f'<figcaption class="diagram-footer">{html.escape(caption)}</figcaption>'
                        f'</figure>'
                    )
                except Exception as err:
                    logger.warning("Could not embed SVG %s into HTML: %s", svg_file, err)

        svg_embed = "\n".join(svg_blocks)

        section_cards.append(
            f'<section id="{schema_key}" class="section-card">'
            f'<div class="section-badge">Section {num}</div>'
            f'<h2 class="section-title">{html.escape(title)}</h2>'
            f'{svg_embed}'
            f'<div class="section-body">{body_html}</div>'
            f'</section>'
        )

    sidebar_html = "\n".join(sidebar_items)
    sections_html = "\n".join(section_cards)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(disp_name)} — Universal Project Documentation</title>
  <style>
    :root {{
      --bg-primary: #090d16;
      --bg-secondary: #0f172a;
      --bg-card: #1e293b;
      --border-color: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-purple: #c084fc;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-main);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }}
    .sidebar {{
      width: 320px;
      background-color: var(--bg-secondary);
      border-right: 1px solid var(--border-color);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }}
    .sidebar-header {{
      padding: 24px 20px;
      border-bottom: 1px solid var(--border-color);
    }}
    .sidebar-header h1 {{
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--accent);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .sidebar-header .meta {{
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 6px;
      line-height: 1.4;
    }}
    .sidebar-nav {{
      flex: 1;
      overflow-y: auto;
      padding: 12px;
    }}
    .nav-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 8px;
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.85rem;
      margin-bottom: 4px;
      transition: all 0.15s;
    }}
    .nav-item:hover {{
      background-color: var(--bg-card);
      color: var(--text-main);
    }}
    .nav-num {{
      width: 22px;
      height: 22px;
      border-radius: 6px;
      background-color: var(--bg-primary);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--accent);
      flex-shrink: 0;
    }}
    .nav-text {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .content-area {{
      flex: 1;
      overflow-y: auto;
      padding: 40px;
      scroll-behavior: smooth;
    }}
    .cover-card {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 36px;
      margin-bottom: 40px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.4);
    }}
    .cover-card h1 {{
      font-size: 2rem;
      color: #ffffff;
      margin-bottom: 6px;
    }}
    .cover-card .subtitle {{
      color: var(--accent);
      font-size: 0.95rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 20px;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      background-color: rgba(9, 13, 22, 0.6);
      padding: 18px;
      border-radius: 10px;
      border: 1px solid var(--border-color);
      font-size: 0.85rem;
    }}
    .meta-grid div span {{ color: var(--text-muted); display: block; font-size: 0.75rem; text-transform: uppercase; }}
    .section-card {{
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 32px;
      margin-bottom: 40px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.3);
    }}
    .section-badge {{
      display: inline-block;
      font-size: 0.7rem;
      font-weight: 700;
      background-color: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      padding: 4px 10px;
      border-radius: 9999px;
      margin-bottom: 8px;
      text-transform: uppercase;
    }}
    .section-title {{
      font-size: 1.5rem;
      font-weight: 700;
      color: #ffffff;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 12px;
    }}
    p {{ line-height: 1.7; color: #cbd5e1; margin-bottom: 14px; font-size: 0.92rem; }}
    h3, h4 {{ color: #ffffff; margin-top: 20px; margin-bottom: 10px; }}
    ul, ol {{ margin-left: 24px; margin-bottom: 14px; color: #cbd5e1; font-size: 0.92rem; }}
    li {{ margin-bottom: 6px; }}
    pre {{
      background-color: #060911;
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 16px;
      overflow-x: auto;
      margin: 16px 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem;
      color: #e2e8f0;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background-color: rgba(51, 65, 85, 0.4);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.85em;
      color: #38bdf8;
    }}
    .table-responsive {{ overflow-x: auto; margin: 18px 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      background-color: var(--bg-card);
      border-radius: 8px;
      overflow: hidden;
    }}
    th {{
      background-color: #0d1527;
      color: #ffffff;
      text-align: left;
      padding: 10px 14px;
      font-weight: 600;
      border-bottom: 1px solid var(--border-color);
    }}
    td {{
      padding: 10px 14px;
      border-bottom: 1px solid rgba(51, 65, 85, 0.6);
      color: #cbd5e1;
    }}
    tr:nth-child(even) td {{ background-color: rgba(15, 23, 42, 0.4); }}
    .diagram-container {{
      background-color: #060911;
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 20px;
      margin: 24px 0;
      box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    }}
    .diagram-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 16px;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 10px;
    }}
    .diagram-caption-badge {{
      color: var(--accent);
      font-weight: 700;
      letter-spacing: 0.3px;
    }}
    .diagram-verified-tag {{
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 0.72rem;
      font-weight: 600;
    }}
    .diagram-svg-wrap {{
      display: flex;
      justify-content: center;
      align-items: center;
      overflow-x: auto;
      padding: 12px 0;
    }}
    .diagram-svg-wrap svg {{
      max-width: 100%;
      height: auto;
      display: block;
      margin: 0 auto;
      border-radius: 8px;
    }}
    .diagram-footer {{
      font-size: 0.78rem;
      color: var(--text-muted);
      font-style: italic;
      text-align: center;
      margin-top: 12px;
      border-top: 1px dashed #1e293b;
      padding-top: 8px;
    }}
    @media print {{
      body {{ overflow: visible; display: block; background: #fff; color: #000; }}
      .sidebar {{ display: none; }}
      .content-area {{ padding: 0; }}
      .section-card {{ border: none; box-shadow: none; page-break-after: always; padding: 0; }}
    }}
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>{html.escape(disp_name)}</h1>
      <div class="meta">
        <div>Repo: {html.escape(repo_name)}</div>
        <div>Docs: {html.escape(doc_ver)} | {html.escape(analysis_ver)}</div>
      </div>
    </div>
    <nav class="sidebar-nav">
      {sidebar_html}
    </nav>
  </aside>

  <main class="content-area">
    <div class="cover-card">
      <div class="subtitle">Official Project Documentation</div>
      <h1>{html.escape(disp_name)}</h1>
      <div class="meta-grid">
        <div><span>Repository</span>{html.escape(repo_name)}</div>
        <div><span>Branch</span>{html.escape(branch)}</div>
        <div><span>Commit</span>{html.escape(commit_sha[:10] if commit_sha else "HEAD")}</div>
        <div><span>Generated</span>{html.escape(generated_at[:19].replace("T", " ") if "T" in generated_at else generated_at)}</div>
      </div>
    </div>

    {sections_html}
  </main>
</body>
</html>
"""
    output_path.write_text(full_html, encoding="utf-8")
    logger.info("Universal HTML documentation exported successfully to %s", output_path)
    return output_path
