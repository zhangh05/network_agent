# Frontend

The frontend is a React 18 + TypeScript + Vite application. It uses Zustand for local state and talks to the backend through typed API helpers in `frontend/src/api`.

## Main Screens

The left sidebar exposes the canonical navigation. Each entry maps to a single-page route and is rendered via `App.tsx`'s `NAV_ITEMS` table — adding a page is a single edit there.

- `AgentWorkbench` (`/workbench`): conversation, runtime timeline, inline tool calls, approvals.
- `PacketAnalysis` (`/packet`): PCAP capture, filter, align, basic LLM assist.
- `RunsPage` (`/runs`): recent run history with trace events.
- `CapabilityCenter` (`/capabilities`): business capability catalog + recommended tools.
- `JobsPage` (`/jobs`): durable background jobs.
- `KnowledgeLibrary` (`/knowledge`): knowledge source/chunk search.
- `ArtifactCenter` (`/artifacts`): artifact list and download.
- `MemoryPage` (`/memory`): governed memory records.
- `CMDBPage` (`/cmdb`): device assets plus region/asset inspection launch into the workbench.
- `RemoteTerminal`: interactive SSH/Telnet connection UI (modal, not a sidebar route).
- `Diagnostics` (`/diagnostics`): runtime health, selfcheck, prompt registry, policies.
- `Settings` (`/settings`): LLM provider and runtime settings.

## Workbench Data Flow

```text
user sends message
  -> append optimistic user message
  -> create one assistant placeholder
  -> WebSocket or HTTP stream
  -> merge backend messages by stable id / role / content / timestamp
  -> render chat + timeline from store
```

The frontend must not duplicate user messages when the final backend message list arrives. Backend messages are the persisted truth; optimistic messages are temporary UI state and must be reconciled, not appended blindly.

## Workspace Contract

Every API helper that touches user data must pass `currentWorkspaceId`. Empty workspace IDs should produce a visible UI error instead of silently calling the backend.

## Approval UI

Approval bubbles subscribe to the unified approval API/SSE. Buttons resolve a durable approval id; they do not directly execute tools. UI must handle idempotent resolve responses without re-opening the same bubble.

## Tool And Capability UI

The visible tool catalog is based on the current 23 network-agent tools. Business capabilities are display metadata from `agent/capabilities/catalog.py`. Frontend labels may be friendly, but API payloads must use canonical tool IDs.

## Validation

```bash
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
```
