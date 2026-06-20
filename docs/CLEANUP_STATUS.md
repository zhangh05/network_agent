# Cleanup Status

Branch: cleanup-doc-rewrite

## Completed

- README rewritten around current runtime pipeline.
- DESIGN rewritten around explicit runtime state, action kernel and finalization.
- docs/ARCHITECTURE rewritten as current package and report map.
- docs/RUNTIME rewritten around current turn flow and finalization metadata.
- docs/API rewritten around current public interface and metadata contract.
- docs/FRONTEND rewritten around metadata-driven inspection.
- docs/CAPABILITIES_AND_TOOLS rewritten with full metadata table and version resolution.
- AGENTS.md rewritten for current turn lifecycle and runtime packages.
- docs/AGENT_HARDENING_STAGES.md updated to remove context_safe/context_compaction references.
- Removed RuntimeLoop references from prompting/blocks.py, loop.py docstring, config_translation service.
- Removed context_compaction.py reference from context_builder.py docstring.
- Added harness/test_doc_cleanup_current_architecture.py.

## Current architecture source

The current runtime architecture is based on RuntimeState and the following packages:

- agent/runtime/state
- agent/runtime/tasking
- agent/runtime/cognition
- agent/runtime/tool_execution
- agent/runtime/output
- agent/runtime/response
- agent/runtime/memory_write
- agent/runtime/observability
- agent/runtime/truth
- agent/runtime/stability

## Metadata contract

- runtime_state_snapshot
- task_signal
- action_trace
- artifact_records
- output_summary
- final_response
- memory_write_plan
- turn_trace
- truth_report
- stability_report

## Local validation request

Run the new documentation cleanup test and existing core runtime suites before PR.
