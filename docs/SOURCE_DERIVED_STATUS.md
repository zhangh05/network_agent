# Source-Derived Status

This file records facts checked from current source and local runtime construction.

## Backend

- Entry point: `backend/main.py`
- Framework: Flask
- Default backend bind: `0.0.0.0:8010`
- Main runtime endpoint: `POST /api/agent/message`
- REMOVED (v2.1.1): `POST /api/agent/run` migrated to `/api/agent/message`

## Frontend

- Source root: `frontend/`
- Stack: React 18, TypeScript, Vite 5, React Router, Zustand, Axios
- Dev server: `5173`
- Dev proxy: `/api` to `VITE_DEV_API_TARGET`, default `http://127.0.0.1:8010`
- Current test inventory: 15 Vitest files and 12 Playwright specs

## Runtime Registry

- Runtime capabilities are defined in `agent/capabilities/builtin.py`.
- Current runtime capability count: 7 total, 4 enabled, 3 planned.
- Current runtime tool registry count: 88 registered tools.
- Current model-visible tool count: 88.
- `GET /api/runtime/summary` exposes these counts for frontend status display.

Registered but not model-visible:

- `knowledge.read_source`

Enabled model-visible runtime tools with extra execution gates:

- `weather.current`, `weather.forecast`, and `news.search` are medium-risk real-time information tools backed by public Web search.
- `shell.exec`, `powershell.exec`, and `python.exec` are high-risk approved execution tools. The LLM can see them, but execution requires approval and allowlisted ids.

## Public Registry API

`GET /api/capabilities` uses `registry.loader.load_capabilities()`, which now projects from the runtime `CapabilityRegistry`. Legacy capability ids such as `config.translate` remain accepted by `get_capability()` as compatibility aliases, but public capability rows use runtime ids.

Current public capability projection:

- enabled: `config_translation`, `knowledge`, `artifact`, `review`
- planned: `topology`, `inspection`, `cmdb`

## Tool Visibility

- `ToolRouter.for_turn(..., allowed_tool_ids=set())` represents an explicit zero-tool turn.
- Default turns expose the full model-visible tool catalog after the registry safety filter. Pure `assistant_chat`, `capability_discovery`, and business turns can all use `web.search`, `web.fetch_summary`, knowledge, artifact, review, and config-translation tools when needed.
- Each OpenAI-compatible tool description includes `tool_id`, `risk`, `source`, and `approval` metadata so the LLM sees the relevant safety context before choosing a tool.
- Capability tools override same-id runtime catalog tools when the capability manifest declares the active business contract. For example, `artifact.list` resolves to `capability:artifact.list`.

## Knowledge And Memory

- Local file upload is exposed through `POST /api/knowledge/upload`.
- Safe knowledge search is exposed through `GET /api/knowledge/search`.
- Unified RAG retrieval lives in `context/retrieval.py`.
- Memory write/confirm can return conflict metadata and updates memory status only — does NOT automatically project into RAG index. RAG projection is a separate, manual operation.

## Workspace API

`GET /api/workspaces` ensures `default` exists, returns it first when present, and includes frontend-facing `name`, `created_at`, `is_default`, compatibility counts, and a `stats` object.
