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
    return (ROOT / relative_path).read_text(encoding="utf-8")


def markdown_links(text: str) -> list[str]:
    return [
        target
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        if "://" not in target and not target.startswith("#")
    ]


def main() -> int:
    from agent.runtime.services import default_runtime_services
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.tool_governance import planner_visible_tool_ids
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    services = default_runtime_services()
    registered = {
        tool.tool_id for tool in services.tool_service.registry.list_all()
    }
    model_visible = {
        tool.tool_id for tool in services.tool_service.registry.list_model_visible()
    }
    canonical = set(CANONICAL_REGISTRY)
    namespace = set(TOOL_NAMESPACE)
    planner_visible = set(planner_visible_tool_ids())

    check(registered == canonical, "runtime registry matches canonical registry")
    check(model_visible == planner_visible, "model-visible tools match planner-visible tools")
    check(canonical == namespace, "canonical registry matches tool namespace")

    required_docs = [
        "README.md",
        "AGENTS.md",
        "docs/API.md",
        "docs/ARCHITECTURE.md",
        "docs/CAPABILITIES_AND_TOOLS.md",
        "docs/FRONTEND.md",
        "docs/RUNTIME.md",
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
        "agent/modules/knowledge/",
        "tool_runtime/canonical_registry.py",
        "GET /api/pcap/session/<sid>",
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
