"""
Shared file-walking logic:
- Respects .gitignore patterns if present
- Detects language by extension
- Skips binary / non-code files
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Generator

# Language detection map
EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".r": "r",
    ".R": "r",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".mdx": "markdown",
    ".txt": "text",
    ".vue": "vue",
    ".svelte": "svelte",
    ".dart": "dart",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".tf": "terraform",
    ".dockerfile": "dockerfile",
}

# Always-skip directory names
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    ".venv", "venv", "env", "dist", "build", ".next",
    ".nuxt", "target", "vendor", ".cache", "coverage",
}

# Extensions we treat as definitely binary / skip
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".webp", ".tiff", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".a",
    ".o", ".class", ".jar", ".war", ".pyc", ".pyo", ".wasm",
    ".mp3", ".mp4", ".wav", ".avi", ".mkv", ".mov", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".lock",
    ".db", ".sqlite", ".sqlite3",
}

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _parse_gitignore(root: Path) -> list[str]:
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        return []
    patterns: list[str] = []
    with gitignore_path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def _is_ignored_by_gitignore(rel_path: str, patterns: list[str]) -> bool:
    """Very lightweight gitignore matching (prefix / suffix / glob-like)."""
    from fnmatch import fnmatch

    parts = Path(rel_path).parts
    for pattern in patterns:
        p = pattern.rstrip("/")
        # Match any path component against a simple pattern
        for part in parts:
            if fnmatch(part, p):
                return True
        # Match the full relative path
        if fnmatch(rel_path, p):
            return True
        if fnmatch(rel_path, f"**/{p}"):
            return True
    return False


def _is_binary_file(path: Path) -> bool:
    """Sniff first 8 KB for null bytes — fast binary detection."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def compute_hash(path: Path) -> str:
    sha = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha.update(chunk)
    except OSError:
        pass
    return sha.hexdigest()


def detect_language(path: Path) -> str | None:
    suffix = path.suffix.lower()
    # Special case: "Dockerfile" with no extension
    if path.name.lower() in ("dockerfile", "dockerfile.dev", "dockerfile.prod"):
        return "dockerfile"
    return EXTENSION_LANGUAGE.get(suffix)


def walk_repo(
    root: Path,
) -> Generator[dict, None, None]:
    """
    Yields dicts with keys: path (str, relative), language, size, content_hash.
    Skips binary files, ignored dirs, and files too large.
    """
    gitignore_patterns = _parse_gitignore(root)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        rel_dir = current.relative_to(root)

        # Prune skipped directories in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not _is_ignored_by_gitignore(str(rel_dir / d), gitignore_patterns)
        ]

        for filename in filenames:
            file_path = current / filename
            suffix = file_path.suffix.lower()

            if suffix in BINARY_EXTENSIONS:
                continue

            rel_path = file_path.relative_to(root)
            rel_str = str(rel_path).replace("\\", "/")

            if _is_ignored_by_gitignore(rel_str, gitignore_patterns):
                continue

            try:
                size = file_path.stat().st_size
            except OSError:
                continue

            if size > MAX_FILE_SIZE_BYTES:
                continue

            if _is_binary_file(file_path):
                continue

            language = detect_language(file_path)

            yield {
                "path": rel_str,
                "language": language,
                "size": size,
                "content_hash": compute_hash(file_path),
            }
