# Frontend

The frontend is a React/Vite app under `frontend/`.

## Stack

- React 18
- TypeScript
- Vite 5
- React Router
- Zustand
- Axios
- Vitest
- Playwright

## App Structure

- Entry: `frontend/src/main.tsx`
- Routes: `frontend/src/app/App.tsx`
- API client: `frontend/src/api/client.ts`
- API modules: `frontend/src/api/index.ts`
- Shared types: `frontend/src/types/index.ts`
- Layouts: `frontend/src/layouts/`
- Pages: `frontend/src/pages/`
- Stores: `frontend/src/stores/`
- Styles: `frontend/src/styles/global.css`

## Pages

- `/workbench`: chat workbench and turn result display
- `/knowledge`: knowledge sources and search
- `/artifacts`: artifact list and preview
- `/reviews`: review item workflow
- `/capabilities`: public capability projection
- `/audit`: runs, traces, tool catalog
- `/settings`: LLM settings

## Runtime Behavior

- API base defaults to `/api`.
- Dev proxy target defaults to `http://127.0.0.1:8010`.
- Agent turns use `TIMEOUTS.agentTurn = 180_000`.
- Workbench chat history persists in `localStorage["na_workbench"]`.
- Session message sync uses `GET /api/sessions/<id>/messages`.

## Tests

Current source contains:

- 11 Vitest files under `frontend/src/test/*.test.tsx`
- 11 Playwright specs under `frontend/e2e/*.spec.ts`
