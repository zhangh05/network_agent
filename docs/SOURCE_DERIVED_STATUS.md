# Source-Derived Status

This file records facts checked from current source and local runtime construction.

## Backend

- Entry point: `backend/main.py`
- Framework: Flask
- Default port: `8010`
- Main runtime endpoint: `POST /api/agent/message`
- Legacy-compatible endpoint: `POST /api/agent/run`

## Frontend

- Source root: `frontend/`
- Stack: React 18, TypeScript, Vite 5, React Router, Zustand, Axios
- Dev server: `5173`
- Dev proxy: `/api` to `VITE_DEV_API_TARGET`, default `http://127.0.0.1:8010`
- Current test inventory: 12 Vitest files and 11 Playwright specs

## Runtime Registry

- Runtime capabilities are defined in `agent/capabilities/builtin.py`.
- Current runtime capability count: 7 total, 4 enabled, 3 planned.
- Current runtime tool registry count: 73 registered tools.
- Current model-visible tool count: 70.
- `GET /api/runtime/summary` exposes these counts for frontend status display.

Registered but not model-visible:

- `command.approved_exec`
- `powershell.approved_script`
- `knowledge.read_source`

## Public Registry API

`GET /api/capabilities` uses `registry.loader.load_capabilities()` and returns the YAML registry projection, not the runtime capability registry.

Current public capability projection:

- enabled: `config.translate`, `config.review`, `knowledge.search`
- planned: `topology.draw`, `inspection.analyze`

## Workspace API

`GET /api/workspaces` ensures `default` exists, returns it first when present, and includes frontend-facing `name`, `created_at`, `is_default`, compatibility counts, and a `stats` object.
