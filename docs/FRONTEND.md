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

## Source Layout

| Path | Purpose |
|---|---|
| `frontend/src/main.tsx` | React entry |
| `frontend/src/app/App.tsx` | routes and app shell |
| `frontend/src/api/client.ts` | Axios wrapper and timeout policy |
| `frontend/src/api/index.ts` | typed API modules |
| `frontend/src/types/index.ts` | shared API-facing types |
| `frontend/src/layouts/` | sidebar, inspector, shell |
| `frontend/src/pages/` | route pages |
| `frontend/src/stores/` | session, workbench, toast state |
| `frontend/src/styles/global.css` | design system and interaction polish |
| `frontend/src/test/` | Vitest tests |
| `frontend/e2e/` | Playwright specs |

## Routes

- `/workbench`: chat workbench, sidebar with active-session recent runs (session-title labels) and source/citation actions, inspector
- `/knowledge`: local upload, artifact import, source list, search
- `/artifacts`: artifact list, preview, next actions
- `/reviews`: human review workflow and review item updates
- `/capabilities`: capability matrix
- `/audit`: runs, traces, tool catalog, runtime events
- `/settings`: LLM provider configuration and diagnostics

## Runtime Behavior

- API base defaults to `/api`.
- Dev proxy target defaults to `http://127.0.0.1:8010`.
- Agent turns use `TIMEOUTS.agentTurn = 180_000`.
- Workbench chat history persists in `localStorage["na_workbench"]`.
- Session message sync uses `GET /api/sessions/<id>/messages`.
- Initial workspace selection prefers `is_default`, then `workspace_id == "default"`, then the first backend item.
- Header version uses `GET /api/version`.
- Workbench runtime status uses `GET /api/runtime/summary`.

## Current UI Notes

- The UI is API-backed, not mock-backed.
- The Knowledge Library uses a custom file picker rather than the browser-native visible file input.
- The Review Center has a user-facing empty state explaining when items appear.
- Global interaction polish lives in `frontend/src/styles/global.css`: page entry, card/table row animation, button press, hover, and modal/toast motion.

## Tests

Current source contains:

- 15 Vitest files under `frontend/src/test/*.test.*`
- 12 Playwright specs under `frontend/e2e/*.spec.ts`

Run:

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run typecheck
npm test -- --run
npm run build
```
