# Architecture

Current source architecture reference.

Pipeline: Input -> RuntimeState -> Evidence -> Planning -> Kernel -> Output -> Response -> Reports -> Snapshot.

Main packages:

- agent/runtime/cognition
- agent/runtime/state
- agent/runtime/tasking
- agent/runtime/output
- agent/runtime/response
- agent/runtime/memory_write
- agent/runtime/observability
- agent/runtime/truth
- agent/runtime/stability

Main reports:

- runtime_state_snapshot
- artifact_records
- output_summary
- final_response
- memory_write_plan
- turn_trace
- truth_report
- stability_report
