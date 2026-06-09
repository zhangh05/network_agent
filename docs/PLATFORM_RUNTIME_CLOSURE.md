# Platform Runtime Closure v0.4

Baseline entering completion: `8cf0a1b` → SSE streaming, rate limiting, LLM orchestrator, context v0.2, lifecycle refactor.

Baseline harness evidence: `1351 passed, 7 skipped, 0 failed`.

## Current Runtime Scope

- Agent chain: `router → context → planner → skill_executor (→ orchestrator for chat/knowledge) → verifier → composer → memory`
- Formal APIs:
  - `POST /api/agent/run` (supports `session_id` v3.1+, `stream=true` SSE v0.4)
  - `POST /api/modules/config-translation/translate`
  - `POST /api/jobs`
  - `GET/POST/PUT/DELETE /api/sessions/*` (10 endpoints, v3.1+)
- Enabled business module: `config_translation`
- Enabled base capability: `knowledge_base` (knowledge_search MVP)
- Agent base capability: `assistant_chat` (not a business module)
- LLM Orchestrator: agentic loop (up to 10 steps) with disabled deterministic fallback
- Session Management: conversation threads with archive/soft-delete/permanent-delete (v3.1+)
- SSE Streaming: `stream=true` for real-time Agent execution progress
- Rate Limiting: IP-based token bucket middleware
- Context v0.2: dynamic budget, semantic dedup, regex-sensitive keys
- Planned only: Topology, Inspection, CMDB

## Closure Rules

- UI must show loading, unavailable, empty, planned, or coming_soon for unavailable data.
- UI must not fabricate jobs, artifacts, reports, tools, inspection data, topology, risks, devices, or provider state.
- Run history is stored in the backend workspace run store, not browser local history.
- **Session history is stored in backend session store** — `localStorage` only holds `na_current_session_id` pointer, never message content (v3.1+).
- Run history stores only safe summaries: run/workspace IDs, intent/capability/skill/module/status, warnings, quality counts, refs, and trace ID.
- **Session metadata is lightweight** — only title, status, run_ids, timestamps. Deletion of session metadata does not affect underlying run records or artifacts.
- Tool Runtime writes only allowlisted ToolResult metadata to observability traces.
- Public Tool invoke HTTP API and Tool Catalog UI exist; policy and approval checks are mandatory.
- Agent may use only the supervised Tool Bridge for explicit low-risk tool requests; high-risk tools require approval.
- No real device execution exists.

## Quality Summary

`quality_summary` is visible through config translation API responses, Agent top-level results, final response summaries, run history, UI recent rows, and trace metadata summaries.

Required counts:

- `source_residue_count`
- `silent_drop_count`
- `unsupported_count`
- `safe_drop_count`
- `review_required_count`

If residue or silent-drop counts are non-zero, the result must produce warning/manual-review state and must not be described as ready for device execution.
