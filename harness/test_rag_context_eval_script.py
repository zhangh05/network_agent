import json
import subprocess
import sys
from pathlib import Path


def test_rag_context_eval_script_passes():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "evaluate_rag_context.py")],
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["metrics"]["knowledge_hit_count"] >= 1
    assert data["metrics"]["memory_hit_count"] >= 1
