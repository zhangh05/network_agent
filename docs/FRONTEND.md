# Frontend Integration

Frontend should treat runtime metadata as the inspection surface.

## Primary result fields

Display these fields when present:

- `final_response`: user-facing response plan and rendered content.
- `artifact_records`: created or registered outputs.
- `output_summary`: artifact and source summary.
- `runtime_state_snapshot`: active task, workflow, step and progress.
- `memory_write_plan`: planned memory candidates and skipped candidates.
- `turn_trace`: structured event list.
- `truth_report`: runtime version, config and capability facts.
- `stability_report`: core runtime checks.

## Recommended panels

| Panel | Source |
|---|---|
| Answer | `final_response.content` |
| Task state | `runtime_state_snapshot` |
| Artifacts | `artifact_records` |
| Trace | `turn_trace.events` |
| Runtime facts | `truth_report` |
| Stability | `stability_report` |

## Streaming

Streaming can continue to show token and event updates. The final result should be normalized around the metadata contract above.

## No duplicated truth

Frontend should not hard-code tool counts, capability counts or runtime stage names. Use `truth_report`, `turn_trace` and `stability_report` from the backend result.
