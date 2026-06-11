# Architecture

This document reflects the current source tree.

## System Shape

```
React/Vite frontend
  -> Flask API (`backend/main.py`)
  -> AgentApp / AgentThread / AgentSession / AgentTurn
  -> RuntimeLoop
  -> LLM runtime + ToolRouter
  -> ToolRuntime, capability handlers, workspace stores
```

## Backend

- Entry point: `backend/main.py`
- Framework: Flask
- Default port: `8010`
- Static frontend serving: `backend/core/paths.py` points `FRONTEND_DIR` to `frontend/`
- Route registration:
  - Main routes live in `backend/main.py`
  - Feature route groups live in `backend/api/*_routes.py`

## Runtime

- Main endpoint: `POST /api/agent/message`
- Legacy endpoint: `POST /api/agent/run`
- Runtime path:
  - `agent/app/facade.py`
  - `agent/core/thread.py`
  - `agent/core/session.py`
  - `agent/core/turn.py`
  - `agent/runtime/loop.py`
- The legacy LangGraph implementation is under `agent/legacy/` and is not the main runtime path.

## Frontend

- Stack: React 18, TypeScript, Vite 5, React Router, Zustand, Axios
- Dev port: `5173`
- Vite proxy: `/api` -> `VITE_DEV_API_TARGET`, default `http://127.0.0.1:8010`
- Main app: `frontend/src/app/App.tsx`
- Pages:
  - `/workbench`
  - `/knowledge`
  - `/artifacts`
  - `/reviews`
  - `/capabilities`
  - `/audit`
  - `/settings`

## Storage

- Workspaces: `workspaces/<workspace_id>/`
- Sessions: `workspaces/<workspace_id>/sessions/`
- Runs: `workspaces/<workspace_id>/runs/`
- Artifacts: `workspaces/<workspace_id>/artifacts/`
- Runtime tool history and approvals: `data/tool_history.json`, `data/tool_approvals.json`

## Registries

There are two capability projections in current source:

- Runtime registry: `agent/capabilities/builtin.py`
- Public YAML registry API: `registry/loader.py` via `GET /api/capabilities`

They are not identical. See [Capabilities and Tools](CAPABILITIES_AND_TOOLS.md).
