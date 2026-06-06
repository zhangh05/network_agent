# backend/core/paths.py

from pathlib import Path
from .settings import NETWORK_AGENT_ROOT, TRANSLATOR_PROJECT_PATH

# Directory paths
SKILLS_DIR = NETWORK_AGENT_ROOT / "skills"
WORKSPACES_DIR = NETWORK_AGENT_ROOT / "workspaces"
MEMORY_DIR = NETWORK_AGENT_ROOT / "memory"
REPORTS_DIR = NETWORK_AGENT_ROOT / "reports"
FRONTEND_DIR = NETWORK_AGENT_ROOT / "frontend"

# Project import
TRANSLATOR_SRC = TRANSLATOR_PROJECT_PATH
