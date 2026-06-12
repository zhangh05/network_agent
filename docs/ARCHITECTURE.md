# Architecture

This document describes the current source tree only.

## System Shape

```text
React/Vite frontend
  -> Flask API (`backend/main.py`)
  -> AgentApp / AgentThread / AgentSession / AgentTurn
  -> RuntimeLoop
  -> context builder + unified RAG retrieval
  -> LLM runtime + ToolRouter
  -> ToolRuntime / capability handlers / workspace stores
```

## Backend

- Entry point: `backend/main.py`
- Framework: Flask
- Default bind: `0.0.0.0:8010`
- Frontend static serving: `backend/core/paths.py` resolves `FRONTEND_DIR`
- Route groups: `backend/api/*_routes.py`

`backend/main.py` directly registers core health, version, agent, session, LLM, module, registry, and memory routes. It then registers runtime, workspace, artifact, job, context, knowledge, and review route groups.

## Runtime Path

The main runtime path is:

1. `POST /api/agent/message`
2. `backend/api/agent_routes.py::agent_message`
3. `agent/app/facade.py`
4. `agent/core/thread.py`
5. `agent/core/session.py`
6. `agent/core/turn.py`
7. `agent/runtime/loop.py`

The legacy-compatible `/api/agent/run` endpoint remains available, but it is not the primary Workbench path.

## Context And RAG

Turn context is assembled from:

- session history
- workspace and runtime metadata
- capability, skill, and tool registry summaries
- knowledge search results
- memory records projected into knowledge
- artifacts and review state when relevant

The unified RAG orchestrator is `context/retrieval.py`. It separates document evidence and memory evidence, applies local token-similarity reranking, deduplicates chunks, and emits citation-ready source cards such as `[K1]` and `[M2]`.

## LLM And Tool Boundary

- LLM settings live under `agent/llm/` and `backend/api/llm_api.py`.
- The runtime prompt is built in `agent/runtime/prompts.py`.
- Tool definitions are exposed through `ToolRouter.model_visible_tools()`.
- LLM-safe tool names use `__` instead of `.`.
- Unknown, disabled, or non-visible tool calls are rejected.

## Storage

Workspace data is file-backed:

| Area | Path |
|---|---|
| Workspaces | `workspaces/<workspace_id>/` |
| Sessions | `workspaces/<workspace_id>/sessions/` |
| Runs | `workspaces/<workspace_id>/runs/` |
| Artifacts | `workspaces/<workspace_id>/artifacts/` |
| Knowledge indexes | `workspaces/<workspace_id>/indexes/` and module knowledge storage |
| Runtime state | `workspaces/_runtime/` |
| Tool history and approvals | `data/tool_history.json`, `data/tool_approvals.json` |

Runtime state and workspace data are operational data, not documentation.

## Registries

There are two capability projections:

- Runtime registry: `agent/capabilities/builtin.py`
- Public YAML registry API: `registry/loader.py` via `GET /api/capabilities`

The runtime registry currently has 7 capabilities. The public YAML projection currently has 5 capability entries. They are intentionally separate surfaces.

## Frontend

- Stack: React 18, TypeScript, Vite 5, React Router, Zustand, Axios
- Source root: `frontend/src/`
- Routes:
  - `/workbench`
  - `/knowledge`
  - `/artifacts`
  - `/reviews`
  - `/capabilities`
  - `/audit`
  - `/settings`

The frontend is a real API client. It does not rely on mocks outside tests.
