# harness/conftest.py
"""Harness configuration — temp dir isolation for tests."""

import os
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def read_frontend_source_text() -> str:
    """Return concatenated Vite/React frontend source for static contract tests."""
    src_root = PROJECT_ROOT / "frontend" / "src"
    chunks: list[str] = []
    for path in sorted(src_root.rglob("*")):
        if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css"}:
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)

# Ensure all temp dirs exist before monkeypatching
_temp_base = Path(tempfile.mkdtemp(prefix="na_test_"))
_temp_mem = _temp_base / "memory_data"
_temp_ws = _temp_base / "workspaces"
_temp_rpts = _temp_base / "reports"
_temp_mem.mkdir(parents=True, exist_ok=True)
_temp_ws.mkdir(parents=True, exist_ok=True)
_temp_rpts.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def temp_dirs(monkeypatch):
    """Redirect memory, workspace, reports to temp dirs for test isolation."""

    mem_dir = _temp_mem
    ws_dir = _temp_ws
    reports_dir = _temp_rpts

    # Monkeypatch ContextStore to use temp directory
    try:
        import context.context_store as _cs
        monkeypatch.setattr(_cs, "_BASE", ws_dir)
    except Exception:
        pass

    # Monkeypatch workspace paths
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws_dir)
    monkeypatch.setattr("workspace.run_store.WS_ROOT", ws_dir)
    # Also patch cached imports to avoid module-load-time reference staleness
    monkeypatch.setattr("tool_runtime.general_tools.WS_ROOT", ws_dir)

    # Set env vars
    monkeypatch.setenv("NETWORK_AGENT_REPORTS_DIR", str(reports_dir))
    monkeypatch.setenv("NETWORK_AGENT_MEMORY_DIR", str(mem_dir))
    monkeypatch.setenv("NETWORK_AGENT_WORKSPACE_DIR", str(ws_dir))

    yield {
        "memory_dir": mem_dir,
        "workspace_dir": ws_dir,
        "reports_dir": reports_dir,
        "base": _temp_base,
    }

    # Cleanup test-generated files but keep dirs
    for f in mem_dir.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    for d in ws_dir.iterdir():
        if d.is_dir():
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass


@pytest.fixture(autouse=True)
def protect_llm_config():
    """Backup and restore real LLM config to prevent test pollution."""
    import agent.llm.settings as mod
    real_path = Path(__file__).resolve().parent.parent / "config" / "LLM_setting.json"
    backup = None
    if real_path.is_file():
        backup = real_path.read_text()
    yield
    if backup is not None:
        real_path.parent.mkdir(exist_ok=True)
        real_path.write_text(backup)


@pytest.fixture
def fresh_workspace(temp_dirs):
    """Get a fresh workspace for a test."""
    from workspace.manager import ensure_workspace
    ensure_workspace("test_ws")
    return "test_ws"


@pytest.fixture
def sample_config():
    """Sample Cisco config for testing."""
    return (
        "hostname R1\n"
        "interface GigabitEthernet0/1\n"
        " ip address 10.1.1.1 255.255.255.0\n"
        " no shutdown\n"
    )
