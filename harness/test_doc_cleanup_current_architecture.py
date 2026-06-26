# harness/test_doc_cleanup_current_architecture.py
"""Documentation checks for current runtime architecture."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    ROOT / "DESIGN.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "RUNTIME.md",
    ROOT / "docs" / "API.md",
    ROOT / "docs" / "FRONTEND.md",
]

REQUIRED_TERMS = [
    "RuntimeState",
    "Output",
    "Response",
    "memory_write_plan",
    "turn_trace",
    "truth_report",
    "stability_report",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_current_docs_exist_and_are_not_empty():
    for path in DOCS:
        assert path.exists(), str(path)
        assert _read(path).strip(), str(path)


def test_docs_reference_current_runtime_reports():
    combined = "\n".join(_read(path) for path in DOCS)
    for term in REQUIRED_TERMS:
        assert term in combined


def test_docs_match_current_runtime_constants_and_api_methods():
    combined = "\n".join(_read(path) for path in DOCS)

    assert "Python 3.13" not in combined
    assert "`GET` | `/api/tools/invoke`" not in combined
    assert "`GET /api/tools/invoke`" not in combined
    assert "max 8 steps" not in combined
    assert "history window (k=8)" not in combined

    assert "Python 3.12+" in combined
    assert "`POST /api/tools/invoke`" in combined
    assert "max 24 steps" in combined
    assert "history window (k=30)" in combined
