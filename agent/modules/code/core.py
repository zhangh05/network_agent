# agent/modules/code/core.py
"""Code search — ripgrep (rg) wrapper with Python grep fallback."""

from __future__ import annotations

import subprocess
import os
import re
from pathlib import Path


def _run_rg(pattern: str, path: str, max_lines: int = 100) -> str:
    args = [
        "rg", "--no-heading", "--line-number", "--color=never",
        "--max-count", str(max_lines), pattern, path,
    ]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=15, env=os.environ)
        return r.stdout.strip() or r.stderr.strip() or ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _grep_fallback(pattern: str, path: str, max_lines: int = 100) -> str:
    lines = []
    try:
        p = Path(path)
        targets = list(p.rglob("*.py")) + list(p.rglob("*.ts")) + list(p.rglob("*.tsx")) + \
                  list(p.rglob("*.js")) + list(p.rglob("*.yaml")) + list(p.rglob("*.yml")) + \
                  list(p.rglob("*.json")) + list(p.rglob("*.md")) + list(p.rglob("*.toml"))
        compiled = re.compile(pattern, re.IGNORECASE)
        for f in targets[:200]:  # limit file count
            try:
                content = f.read_text(errors="ignore")
                for i, line in enumerate(content.split("\n"), 1):
                    if compiled.search(line):
                        lines.append(f"{f}:{i}:{line[:200]}")
                        if len(lines) >= max_lines:
                            return "\n".join(lines)
            except Exception:
                pass
    except Exception:
        pass
    return "\n".join(lines)


def search_code(
    pattern: str,
    directory: str = ".",
    file_type: str = "",
    max_results: int = 50,
) -> dict:
    """Search codebase for pattern using ripgrep or Python fallback.

    Args:
        pattern: Regex or literal pattern to search.
        directory: Search root. Defaults to current directory.
        file_type: Optional file type filter (py, ts, js, yaml, etc).
        max_results: Max matching lines to return (default 50).
    """
    path = str(Path(directory).resolve())
    if not os.path.isdir(path):
        return {"ok": False, "error": f"Directory not found: {directory}"}

    # Try ripgrep first (fast, native)
    result = _run_rg(pattern, path, max_results)
    if not result and not file_type:
        result = _run_rg(pattern, path, max_results)

    # Python fallback
    if not result:
        if file_type:
            glob_pattern = path
            result = _run_rg(pattern, path, max_results)  # rg handles file types natively
            if not result:
                result = _grep_fallback(pattern, path, max_results)
        else:
            result = _grep_fallback(pattern, path, max_results)

    if not result:
        return {"ok": True, "matches": [], "count": 0, "message": "No matches found"}

    lines = result.strip().split("\n")
    return {
        "ok": True,
        "matches": lines[:max_results],
        "count": len(lines[:max_results]),
    }
