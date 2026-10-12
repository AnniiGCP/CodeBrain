"""
backend/docgen/json_exporter.py
-------------------------------
Exports structured repository documentation and Knowledge Graph to JSON format.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgen.secret_redactor import redact_secrets

logger = logging.getLogger(__name__)


def generate_json_documentation(
    repo_id: str,
    repo_name: str,
    sections: list,
    master_md: str,
    output_path: Path,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Generates structured JSON representation of the entire documentation suite."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sec_list = []
    for sec in sections:
        num = getattr(sec, "section_number", 0) or (sec.get("section_number") if isinstance(sec, dict) else 0)
        title = getattr(sec, "title", "") or (sec.get("title") if isinstance(sec, dict) else "")
        key = getattr(sec, "schema_key", "") or (sec.get("schema_key") if isinstance(sec, dict) else "")
        filename = getattr(sec, "filename", "") or (sec.get("filename") if isinstance(sec, dict) else "")
        content = getattr(sec, "content", "") or (sec.get("content") if isinstance(sec, dict) else "")
        status = getattr(sec, "status", "fully_generated") or (sec.get("status") if isinstance(sec, dict) else "fully_generated")
        has_diagram = getattr(sec, "has_diagram", False) or (sec.get("has_diagram") if isinstance(sec, dict) else False)

        sec_list.append({
            "section_number": num,
            "title": title,
            "schema_key": key,
            "filename": filename,
            "status": status,
            "has_diagram": has_diagram,
            "content": redact_secrets(content),
        })

    data = {
        "repo_id": repo_id,
        "repo_name": repo_name,
        "metadata": metadata or {},
        "total_sections": len(sec_list),
        "sections": sec_list,
        "master_markdown": redact_secrets(master_md),
    }

    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Universal JSON documentation exported successfully to %s", output_path)
    return output_path
