# Architecture

Current source architecture reference.

Pipeline: UserInput -> TurnContext -> SceneDecision -> RuntimeState -> EvidencePipeline -> CapabilityRouter -> SkillManifest -> ToolBundle -> ToolPlannerV2 -> PromptArchitecture -> ActionExecutionKernel -> Output -> Reports -> Snapshot.

Main packages:

- agent/runtime/cognition
- agent/runtime/state
- agent/runtime/tasking
- agent/runtime/tool_execution (ToolRuntime pipeline, ToolRouter)
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
