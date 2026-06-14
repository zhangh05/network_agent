# tool_runtime/general_tools/__init__.py
"""General Tools — v2.1.1 split architecture.

This package provides modular tool handlers organized by category.
The base module (tool_runtime.general_tools_base) contains the full
implementation and registry. Sub-modules provide categorized access.

Split structure:
  general_tools/
  ├── __init__.py      ← re-exports from general_tools_base (backward compat)
  ├── web_tools.py      ← web/search/weather/news/fetch
  ├── memory_tools.py   ← memory CRUD/profile
  ├── skill_tools.py    ← skill load/create/inspect
  ├── session_tools.py  ← session/run/snapshot/export
  ├── file_tools.py     ← file read/write/edit/patch
  ├── command_tools.py  ← shell/powershell/slash
  ├── artifact_tools.py ← artifact search/save/tag
  ├── pdf_tools.py      ← pdf extract
  └── agent_tools.py    ← agent spawn/team
"""

# Re-export everything from the base module for backward compatibility
from tool_runtime.general_tools_base import *  # noqa: F401 F403
