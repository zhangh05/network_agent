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

    # Monkeypatch JSONL store to use temp directory
    _original_init = None
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        _original_init = JSONLMemoryStore.__init__

        def _patched_init(self, data_dir: str = ""):
            self._dir = mem_dir
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path = self._dir / "memories.jsonl"
            self._deleted_path = self._dir / ".deleted_memories.json"
            self._migrate_old_file = lambda: None

        monkeypatch.setattr(
            "memory.backends.jsonl_store.JSONLMemoryStore.__init__",
            _patched_init,
        )
    except Exception:
        pass

    # Monkeypatch workspace paths
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws_dir)
    monkeypatch.setattr("workspace.run_store.WS_ROOT", ws_dir)
    monkeypatch.setattr("workspace.artifact_store.WS_ROOT", ws_dir)

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
