# backend/core/paths.py

from pathlib import Path
from .settings import NETWORK_AGENT_ROOT

# Directory paths
SKILLS_DIR = NETWORK_AGENT_ROOT / "skills"
WORKSPACES_DIR = NETWORK_AGENT_ROOT / "workspaces"
MEMORY_DIR = NETWORK_AGENT_ROOT / "memory"
REPORTS_DIR = NETWORK_AGENT_ROOT / "reports"
FRONTEND_DIR = NETWORK_AGENT_ROOT / "frontend" / "dist"
MODULES_DIR = NETWORK_AGENT_ROOT / "modules"

# Config translation module (embedded — no external repo)
TRANSLATOR_EMBEDDED_DIR = MODULES_DIR / "config_translation" / "core"
