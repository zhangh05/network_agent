# Network Agent Frontend

React/Vite frontend for Network Agent.

## Run

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev -- --host 0.0.0.0
```

The dev server listens on port `5173` and proxies `/api` to `VITE_DEV_API_TARGET`, defaulting to `http://127.0.0.1:8010`.

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

- `src/app/App.tsx`: routes and top-level shell
- `src/api/client.ts`: Axios wrapper and timeout policy
- `src/api/index.ts`: API modules
- `src/pages/`: route pages
- `src/layouts/`: sidebar, inspector, app layout
- `src/stores/`: session, workbench, toast state
- `src/types/index.ts`: shared API-facing types
- `src/styles/global.css`: design system and interaction polish
- `src/test/`: Vitest tests
- `e2e/`: Playwright specs

## Current Test Inventory

- 15 Vitest files under `src/test/*.test.*`
- 12 Playwright specs under `e2e/*.spec.ts`

## Commands

```bash
npm run typecheck
npm test -- --run
npm run build
npm run e2e
```

## Notes

- Agent turns use `TIMEOUTS.agentTurn = 180_000`.
- Workbench history persists to `localStorage["na_workbench"]`.
- Capability state and tool counts come from backend APIs.
- The frontend is a real API client; mocks are limited to tests.
