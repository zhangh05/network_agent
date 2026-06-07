# Platform Runtime Closure v0.2

Baseline entering completion: `ac6cadd`.

Baseline harness evidence provided for remote main: `850 passed, 7 skipped, 0 failed`.

## Current Runtime Scope

- Agent chain: `router → context → planner → executor → verifier → composer → memory`
- Formal APIs: `POST /api/agent/run`, `POST /api/modules/config-translation/translate`, `POST /api/jobs`
- Enabled business module: `config_translation`
- Agent base capability: `assistant_chat` (not a business module)
- Planned only: Topology, Inspection, CMDB, Knowledge

## Closure Rules

- UI must show loading, unavailable, empty, planned, or coming_soon for unavailable data.
- UI must not fabricate jobs, artifacts, reports, tools, inspection data, topology, risks, devices, or provider state.
- Run history is stored in the backend workspace run store, not browser local history.
- Run history stores only safe summaries: run/workspace IDs, intent/capability/skill/module/status, warnings, quality counts, refs, and trace ID.
- Tool Runtime writes only allowlisted ToolResult metadata to observability traces.
- No public Tool invoke HTTP API or UI exists.
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
