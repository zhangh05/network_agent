#!/usr/bin/env python3
"""Verify that general tools are genuinely split out of general_tools_base."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import inspect
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GENERAL_DIR = ROOT / "tool_runtime" / "general_tools"
BASE = ROOT / "tool_runtime" / "general_tools_base.py"
EXPECTED_RUNTIME_COUNT = 88

FORBIDDEN_PATTERNS = {
    "_HANDLERS": re.compile(r"_HANDLERS"),
    "lazy_import": re.compile(r"lazy_import"),
    "base_handle_import": re.compile(r"from\s+tool_runtime\.general_tools_base\s+import\s+handle_"),
    "base_alias_import": re.compile(r"import\s+tool_runtime\.general_tools_base\s+as\s+_b"),
    "module_spoof": re.compile(r"__module__\s*=\s*__name__"),
    "return_handlers": re.compile(r"return\s+_HANDLERS"),
}


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"{status}: {name}{suffix}")
    return ok


def _source_files() -> list[Path]:
    paths = sorted(GENERAL_DIR.glob("*.py"))
    if BASE.exists():
        paths.append(BASE)
    return paths


def main() -> int:
    from agent.runtime.services import default_runtime_services
    from tool_runtime.general_tools import ALL_GENERAL_TOOLS

    failures = 0

    if BASE.exists():
        text = BASE.read_text()
        line_count = len(text.splitlines())
        failures += not _check(
            "general_tools_base.py is shim-sized",
            line_count < 200,
            f"{line_count} lines",
        )
        failures += not _check(
            "general_tools_base.py contains no handler bodies",
            "def handle_" not in text,
        )
        failures += not _check(
            "general_tools_base.py is not the main registry",
            "ALL_GENERAL_TOOLS" not in text,
        )
    else:
        _check("general_tools_base.py removed", True)

    for path in _source_files():
        text = path.read_text()
        rel = path.relative_to(ROOT)
        for name, pattern in FORBIDDEN_PATTERNS.items():
            failures += not _check(
                f"no forbidden {name} in {rel}",
                pattern.search(text) is None,
            )

    ids = [spec.tool_id for spec, _ in ALL_GENERAL_TOOLS]
    duplicates = sorted(tid for tid, count in Counter(ids).items() if count > 1)
    failures += not _check("ALL_GENERAL_TOOLS has no duplicates", not duplicates, str(duplicates))

    for spec, handler in ALL_GENERAL_TOOLS:
        body = inspect.unwrap(handler)
        filename = inspect.getsourcefile(handler) or ""
        body_filename = inspect.getsourcefile(body) or ""
        module = getattr(handler, "__module__", "")
        body_module = getattr(body, "__module__", "")
        failures += not _check(
            f"{spec.tool_id} handler not in general_tools_base.py",
            not filename.endswith("general_tools_base.py"),
            filename,
        )
        failures += not _check(
            f"{spec.tool_id} unwrapped body is in a general_tools submodule",
            str(GENERAL_DIR) in body_filename and not body_filename.endswith("general_tools_base.py"),
            body_filename,
        )
        failures += not _check(
            f"{spec.tool_id} handler module points to submodule",
            module.startswith("tool_runtime.general_tools.") and module != "tool_runtime.general_tools",
            module,
        )
        failures += not _check(
            f"{spec.tool_id} unwrapped body module points to submodule",
            body_module.startswith("tool_runtime.general_tools.") and body_module != "tool_runtime.general_tools",
            body_module,
        )

    svc = default_runtime_services()
    reg = svc.tool_service.registry
    all_tools = reg.list_all()
    visible = reg.list_model_visible()
    failures += not _check("runtime registry count is 88", len(all_tools) == EXPECTED_RUNTIME_COUNT, str(len(all_tools)))
    failures += not _check("model-visible count is 88", len(visible) == EXPECTED_RUNTIME_COUNT, str(len(visible)))

    if failures:
        print(f"FAIL: {failures} split checks failed")
        return 1
    print("PASS: general tools split is real")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
