import subprocess
import sys
from pathlib import Path


def test_inspect_agent_kernel_script_passes_cleanly():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "inspect_agent_kernel.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert "Traceback" not in output
    assert "❌" not in output
    assert result.returncode == 0, output
