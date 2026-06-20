# Network Agent

Network Agent is a local runtime for network engineering workflows.

## Runtime pipeline

```text
UserInput -> SceneDecision -> RuntimeState -> Evidence -> Planner -> Prompt -> ActionKernel -> Output -> Response -> MemoryPlan -> Trace -> Truth -> Stability -> Snapshot
```

## Directories

```text
agent/core/
agent/runtime/cognition/
agent/runtime/state/
agent/runtime/tasking/
agent/runtime/tool_execution/
agent/runtime/output/
agent/runtime/response/
agent/runtime/memory_write/
agent/runtime/observability/
agent/runtime/truth/
agent/runtime/stability/
backend/
frontend/
harness/
```

## Runtime metadata

```text
runtime_state_snapshot
task_signal
action_trace
artifact_records
output_summary
final_response
memory_write_plan
turn_trace
truth_report
stability_report
```

## Tests

```bash
python -m pytest harness/test_agent_core_finalization_refactor.py -q
python -m pytest harness/test_runtime_state_task_workflow_main_path.py harness/test_runtime_state_task_workflow_refactor.py -q
```
