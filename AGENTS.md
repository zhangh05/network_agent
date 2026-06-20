# Agent Runtime

This document describes the current Agent runtime architecture.

## Turn lifecycle

```
UserInput
  -> TurnContext
  -> SceneDecision
  -> RuntimeState / TaskWorkflow
  -> Context / Memory / Knowledge (EvidencePipeline)
  -> ToolPlannerV2
  -> PromptCompiler
  -> LLM sampling
  -> ActionPlanner -> ActionExecutor (RiskPolicy -> ApprovalGate -> Dispatch)
  -> ResultCollector -> ArtifactPlanner -> ArtifactWriter -> ArtifactRegistry
  -> OutputSummarizer
  -> ResponseComposer
  -> MemoryWritePlanner
  -> ObservabilityCollector
  -> TruthReporter
  -> StabilityGate
  -> RuntimeStateSnapshot
  -> FinalResponse
```

## Runtime packages

| Package | Purpose |
|---------|---------|
| `agent/runtime/context_builder.py` | Builds TurnContext from session, turn, and services |
| `agent/runtime/cognition/` | SceneDecision, EvidencePipeline, PromptCompiler, ToolPlannerV2 |
| `agent/runtime/state/` | RuntimeState, TaskState, WorkflowState, StepState, hooks |
| `agent/runtime/tasking/` | TaskDetector, TaskPlanner, StepExecutor, CompletionEvaluator |
| `agent/runtime/actions/` | ActionPlan, RiskPolicy, ApprovalGate, ActionExecutor |
| `agent/runtime/tool_execution/` | ToolExecutionPipeline (orchestrates ActionExecutor) |
| `agent/runtime/output/` | ResultCollector, ArtifactPlanner, ArtifactWriter, ArtifactRegistry |
| `agent/runtime/response/` | ResponsePolicy, ResponseComposer, ResponseRenderer |
| `agent/runtime/memory_write/` | MemoryWritePlanner, MemoryRiskFilter, MemoryDedupe |
| `agent/runtime/observability/` | ObservabilityCollector, ObservabilityExporter, TurnTrace |
| `agent/runtime/truth/` | VersionTruth, ConfigTruth, CapabilityTruth, TruthReporter |
| `agent/runtime/stability/` | StabilityGate, StabilityChecks |

## Runtime metadata keys

Each turn produces these entries in `ctx.metadata`:

| Key | Source |
|-----|--------|
| `runtime_state_snapshot` | RuntimeStateSnapshotter |
| `task_signal` | TaskDetector |
| `action_trace` | ActionAuditTrail |
| `artifact_records` | ArtifactRegistry |
| `output_summary` | OutputSummarizer |
| `final_response` | ResponseComposer |
| `memory_write_plan` | MemoryWritePlanner |
| `turn_trace` | ObservabilityCollector |
| `truth_report` | TruthReporter |
| `stability_report` | StabilityGate |

## Tool execution

Tools are registered in `tool_runtime/canonical_registry.py`. Each tool call goes through:

```
ActionPlanner -> RiskPolicy -> ApprovalGate -> ToolDispatcher -> ResultNormalizer -> ResultScanner -> ActionAuditTrail
```

High-risk tools (`host.shell.exec`, `host.python.exec`) trigger approval gates.

## Session management

- Each session maintains an independent message history.
- `SessionMessageStore` persists to `workspaces/{ws}/sessions/{sid}/messages/`.
- Supports checkpoint, rewind, and export.

## Sub-agents

`agent.spawn` and `agent.team.run` support multi-agent collaboration. Primary mode is single agent.

## Capability-first Execution Architecture

The runtime now uses a capability-first execution model.

Definitions:

- Skill: a CapabilityPackage-derived user-facing business entry.
- CapabilityPackage: internal business capability declaration.
- Business Module: domain implementation service. Current modules are config_translation, config_analysis, and pcap_analysis.
- Platform Service: infrastructure service such as workspace, knowledge, memory, artifact, runtime, report, and web.
- Tool: callable adapter. LLM-visible business tools are directory-level tools such as config.analysis.run and pcap.analysis.run.

Old fine-grained tools such as network.config.* and network.pcap.* are internal compatibility adapters and must not be selected directly.

See [docs/CAPABILITY_FIRST_ARCHITECTURE.md](docs/CAPABILITY_FIRST_ARCHITECTURE.md).
