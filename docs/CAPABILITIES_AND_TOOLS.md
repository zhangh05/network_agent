# Capabilities

Current runtime capability reference.

Runtime facts come from source modules under `agent/runtime/truth/`.

## Runtime metadata

Each turn produces the following metadata entries managed by the finalization kernels:

| Key | Description |
|-----|-------------|
| `RuntimeState` | Aggregate runtime state including task, workflow, step, artifact, and action |
| `runtime_state_snapshot` | Lightweight snapshot of active task, step, progress, approvals |
| `task_signal` | Detected task intent (new_task / continue_task / cancel_task / none) |
| `action_trace` | Audit trail of all action executions in the turn |
| `artifact_records` | Registry of produced artifacts with kind, path, and status |
| `output_summary` | Summary of all output sources and artifact IDs for the step |
| `final_response` | Composed response with type, content, and artifact references |
| `memory_write_plan` | Candidates for memory persistence (plan only, not persisted) |
| `turn_trace` | Observability events collected across the turn |
| `truth_report` | Version, config, and capability snapshot |
| `stability_report` | Gate check results for metadata, removed-stage, and residue scans |

## Tool registry

Tools are registered in `tool_runtime/canonical_registry.py`. The count is dynamic and depends on loaded modules. ToolRouter builds a per-turn model-visible tool list from the planner output.

## Version source

Version is resolved by `agent/runtime/truth/version.py`:

1. `agent.__version__` (if defined)
2. `pyproject.toml` project version (if present)
3. Fallback to hardcoded value with `version_fallback_used` warning
