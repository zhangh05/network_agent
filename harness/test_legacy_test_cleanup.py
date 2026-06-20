# harness/test_legacy_test_cleanup.py
"""Checks that tests no longer encode removed runtime chains."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harness"

REMOVED_TEST_PHRASES = [
    "RuntimeLoop",
    "tool_dispatch",
    "context_safe",
    "context_compaction",
    "Backward-compatible",
    "legacy wrapper",
    "compatibility wrapper",
]

CURRENT_REQUIRED_TERMS = [
    "RuntimeState",
    "ActionExecutionKernel",
    "artifact_records",
    "output_summary",
    "final_response",
    "memory_write_plan",
    "turn_trace",
    "truth_report",
    "stability_report",
]


def _py_files():
    return [
        p for p in HARNESS.rglob("*.py")
        if "__pycache__" not in str(p)
    ]


def test_harness_does_not_encode_removed_runtime_docs():
    hits = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        for phrase in REMOVED_TEST_PHRASES:
            if phrase in text:
                if path.name == "test_legacy_test_cleanup.py":
                    continue
                hits.append(f"{path.relative_to(ROOT)}: {phrase}")
    assert not hits, "\n".join(hits)


def test_current_core_tests_reference_finalization_contract():
    combined = "\n".join(p.read_text(encoding="utf-8") for p in _py_files())
    for term in CURRENT_REQUIRED_TERMS:
        assert term in combined, f"Missing term in harness: {term}"
