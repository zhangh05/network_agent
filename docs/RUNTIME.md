# Runtime

This document describes the current runtime flow.

## Turn flow

Input -> TurnContext -> RuntimeState -> Evidence -> Tool planning -> Prompt compilation -> Action processing -> Step update -> Finalization -> Snapshot.

## State preparation

The context builder creates TurnContext, attaches the session, computes scene decision, prepares runtime state, selects the current task and step, then builds evidence and safe context.

## Action processing

The runtime processes model tool calls through the action kernel. Each tool call is wrapped in a ToolInvocation and dispatched by the ToolRuntime module that owns the tool. The module orchestrates the tool execution through ToolRouter; the agent does not directly call arbitrary tools. A skill does not bypass its owning module. Each execution produces a ToolResult which is recorded into action trace metadata and consumed by the finalization layer. ToolResult content is summarized before inclusion in LLM context to avoid prompt overflow.

No ssh, telnet, snmp or nmap tools are registered. Remote device access is not supported by the current tool set. A public tool HTTP API is policy-gated and must go through the approval gate for high-risk actions.

## Finalization

After action processing, the runtime runs these kernels:

- Output Kernel
- Response Composer
- Memory Write Planner
- Observability Collector
- Truth Reporter
- Stability Gate

Finalization writes:

- artifact_records
- output_summary
- final_response
- memory_write_plan
- turn_trace
- truth_report
- stability_report

Runtime state is saved after finalization so task, step and artifact changes are present in the final snapshot.

## Metadata contract

The current runtime inspection surface is metadata-based. Frontend, tests and diagnostics should read structured metadata rather than infer state from natural-language text. The primary entry point is POST /api/agent/message which returns the agent result containing all metadata keys.

Required keys after an action phase:

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

## Output contract

Safe artifact writes are limited to markdown, txt, json, csv and log. Other artifact kinds are registered only.

## Memory write contract

Memory writing is plan-only in this stage. The runtime produces MemoryWritePlan and filters sensitive candidates, but it does not persist accepted candidates to a memory database.
