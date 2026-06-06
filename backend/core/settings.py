# backend/core/settings.py

import os
import subprocess
from pathlib import Path

# Project roots
NETWORK_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent
TRANSLATOR_PROJECT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "codex_net_trans" / "network-translator"

# Port
UNIFIED_PORT = int(os.environ.get("NETWORK_AGENT_PORT", "8010"))

# Build commit
def _resolve_build_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            cwd=str(TRANSLATOR_PROJECT_PATH)
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"

BUILD_COMMIT = _resolve_build_commit()

# App identity
APP_NAME = "network_agent"
TRANSLATOR_ENTRY = "translate_bundle"
API_MODE = "unified"
SWITCH_ROUTER_STATUS = "BETA_READY"
PRODUCT_READY = False
FIREWALL_STATUS = "PARTIAL"
