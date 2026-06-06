# RETIRED SURFACE — HISTORICAL CODE ONLY

This directory contains retired/historical code from the network_agent project's early prototyping phase.

## Contents

| Directory | Description | Status |
|-----------|-------------|--------|
| `apps/agent_service/` | Old GraphAgent service (port 8020) | **RETIRED** — replaced by `agent/` LangGraph runtime |
| `apps/translator_service/` | Old translator service wrapping `network-translator` | **RETIRED** — replaced by `modules/config_translation/` |

## Important

- None of this code is imported, called, or referenced by the current runtime.
- It is preserved here solely as historical reference.
- Do NOT import, use, or restore any module from this directory.
- Do NOT reference paths or APIs from this directory in current documentation.
- The `/api/translate` endpoint in `translator_service/app.py` is a **retired surface** — the current translate API is `POST /api/modules/config-translation/translate`.
