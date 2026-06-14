"""harness/test_tool_id_baseline_files.py

v2.1.3: Test that baseline files exist, are consistent, and the
compare script uses repo files (not /tmp).
"""

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BL = ROOT / "baselines" / "tool_ids_v2.1.1-full-closure.txt"
GENERAL_BL = ROOT / "baselines" / "general_tool_ids_v2.1.1-full-closure.txt"


def _read_ids(path: Path) -> list[str]:
    ids = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("count "):
            continue
        ids.append(line)
    return ids


# ── Baseline file existence ──

def test_runtime_baseline_exists():
    assert RUNTIME_BL.exists(), f"Missing {RUNTIME_BL}"


def test_general_baseline_exists():
    assert GENERAL_BL.exists(), f"Missing {GENERAL_BL}"


# ── No duplicates ──

def test_runtime_baseline_no_duplicates():
    ids = _read_ids(RUNTIME_BL)
    assert len(ids) == len(set(ids)), f"Runtime baseline has duplicates"


def test_general_baseline_no_duplicates():
    ids = _read_ids(GENERAL_BL)
    assert len(ids) == len(set(ids)), f"General baseline has duplicates"


# ── Runtime baseline matches current runtime ──

def test_runtime_baseline_matches_current():
    from agent.runtime.services import default_runtime_services
    svc = default_runtime_services()
    reg = svc.tool_service.registry
    current = sorted(t.tool_id for t in reg.list_all())

    baseline_ids = sorted(_read_ids(RUNTIME_BL))
    assert current == baseline_ids, (
        f"Runtime baseline mismatch:\n"
        f"  Baseline: {len(baseline_ids)} ids\n"
        f"  Current:  {len(current)} ids\n"
        f"  Added:    {sorted(set(current) - set(baseline_ids))}\n"
        f"  Removed:  {sorted(set(baseline_ids) - set(current))}"
    )


# ── General baseline matches ALL_GENERAL_TOOLS ──

def test_general_baseline_matches_current():
    from tool_runtime.general_tools import ALL_GENERAL_TOOLS
    general = sorted(spec.tool_id for spec, _ in ALL_GENERAL_TOOLS)

    baseline_ids = sorted(_read_ids(GENERAL_BL))
    assert general == baseline_ids, (
        f"General baseline mismatch:\n"
        f"  Baseline: {len(baseline_ids)} ids\n"
        f"  Current:  {len(general)} ids\n"
        f"  Added:    {sorted(set(general) - set(baseline_ids))}\n"
        f"  Removed:  {sorted(set(baseline_ids) - set(general))}"
    )


# ── compare_tool_id_baseline.py uses repo files (not /tmp) ──

def test_compare_script_uses_repo_defaults():
    """The compare script must default to baselines/ in repo, not /tmp."""
    script_path = ROOT / "scripts" / "compare_tool_id_baseline.py"
    content = script_path.read_text()

    # Must reference baselines/ directory
    assert "baselines" in content, "compare_tool_id_baseline.py must reference baselines/"

    # Must NOT hardcode /tmp as default
    assert '"/tmp/tool_ids_baseline.txt"' not in content, (
        "compare_tool_id_baseline.py must not default to /tmp"
    )
    assert '"/tmp/general_ids_baseline.txt"' not in content, (
        "compare_tool_id_baseline.py must not default to /tmp"
    )
