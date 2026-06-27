#!/usr/bin/env python3
"""Validate current documentation against current runtime surfaces."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    marker = "PASS" if condition else "FAIL"
    print(f"[{marker}] {message}")
    if not condition:
        failures.append(message)


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def markdown_links(text: str) -> list[str]:
    return [
        target
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        if "://" not in target and not target.startswith("#")
    ]


def main() -> int:
    from tool_runtime.manifest_registry import MANIFESTS

    check(len(MANIFESTS) >= 70, "manifests registry has 70+ tools")

    required_docs = [
        "README.md",
        "AGENTS.md",
        "DESIGN.md",
        "STRUCTURE.md",
        "docs/API.md",
        "docs/ARCHITECTURE.md",
        "docs/FRONTEND.md",
        "docs/backend/API_CONTRACT.md",
        "docs/storage/STORAGE_BOUNDARIES.md",
    ]
    for path in required_docs:
        check((ROOT / path).is_file(), f"{path} exists")

    readme = read("README.md")
    for target in markdown_links(readme):
        check((ROOT / target).exists(), f"README link exists: {target}")

    combined_docs = "\n".join(read(path) for path in required_docs)
    required_current_refs = [
        "POST /api/agent/message",
        "WebSocket",
        "Zustand",
        "Virtuoso",
        "manifest_registry.py",
        "workspace_id",
    ]
    for reference in required_current_refs:
        check(reference in combined_docs, f"documents current surface: {reference}")

    print(
        f"\n{len(failures)} failure(s)"
        if failures
        else "\nDocumentation and runtime surfaces are consistent."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
