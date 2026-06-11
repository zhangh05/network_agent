# Network Agent Frontend

React/Vite frontend for Network Agent.

## Run

```bash
cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev
```

The dev server listens on `http://127.0.0.1:5173` and proxies `/api` to `VITE_DEV_API_TARGET`, defaulting to `http://127.0.0.1:8010`.

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
- `src/test/`: Vitest tests
- `e2e/`: Playwright specs

## Current Test Inventory

- 11 Vitest files under `src/test/*.test.tsx`
- 11 Playwright specs under `e2e/*.spec.ts`

## Commands

```bash
npm run typecheck
npm run test
npm run build
npm run e2e
```

## Notes

- Agent turns use a long timeout policy: `TIMEOUTS.agentTurn = 180_000`.
- Workbench history persists to `localStorage["na_workbench"]`.
- Capability state is read from the public backend API; the frontend does not hardcode tool counts or capability status.
