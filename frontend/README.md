# Network Agent — Frontend Workbench v1.0

> Capability-driven Agent Workbench — single-page React 18 + TypeScript 5 + Vite 5 + React Router 6 + Zustand 4.

## Quick start

```bash
npm install
npm run dev      # starts on http://localhost:5173 with /api proxied to 127.0.0.1:8010
npm run typecheck
npm run build
npm run test
```

## Layout

Three-column app, fully capability-driven. Pages render **only** what the backend returns. No hardcoded tool counts or capability states.

| Column | Page | Route |
|--------|------|-------|
| Left | Workspace / Sessions / Recent Runs | always visible |
| Center | AgentWorkbench / KnowledgeLibrary / ArtifactCenter / ReviewCenter / CapabilityCenter / RuntimeAudit / Settings | per-route |
| Right | Turn Inspector | AgentWorkbench only |

## Stack

- React 18, TypeScript 5 strict, Vite 5
- React Router 6 (no nested layouts — page-level `AppLayout` with `cols` prop)
- Zustand 4 for cross-page state (workspace, session, theme, UI prefs)
- Axios for HTTP; errors uniformly converted to `ApiError`
- Vitest + @testing-library/react + happy-dom

## Architecture

```
src/
├── app/App.tsx            ← top-level router + theme bootstrap
├── api/
│   ├── client.ts          ← axios wrapper → ApiError
│   └── index.ts           ← 10 API modules (agent/sessions/...)
├── types/index.ts         ← 1:1 mapping to backend dataclasses
├── stores/
│   ├── session.ts         ← workspace/session/UI state (persisted)
│   ├── workbench.ts       ← chat history + latest result
│   └── toast.ts           ← global toast
├── layouts/
│   ├── AppLayout.tsx      ← three-column grid
│   ├── Sidebar.tsx        ← left column
│   └── Inspector.tsx      ← right column (collapsible sections)
├── components/
│   ├── common.tsx         ← AsyncView / Empty / Error / Loading / Badge / StatusDot / Code / Collapsible / useAsync
│   └── ToastHost.tsx
├── pages/                 ← 7 page components
└── test/                  ← 10 test files + mockServer helper
```

## Hard rules

- Frontend never computes business logic (no diff, no scoring, no extraction).
- No hardcoded `Tool count = 73` or capability status.
- Planned capabilities render their status but **never** an invoke button.
- All `ApiError` thrown at one place (`apiRequest`); pages render the error state via `AsyncView`.
- Empty / loading / error / success are four states that each list page must handle.

## Legacy

`frontend/index.html` (pre-v1.0 single-file) is preserved as `frontend/legacy/index.html.legacy` for reference and rollback; it is not served by Vite and is not part of the v1.0 build.
