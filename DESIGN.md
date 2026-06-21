# Current Runtime Design

This document describes the current source architecture only.

## Principles

1. Runtime state is explicit. Session, workspace, task, workflow, step, action and artifact state are first-class runtime objects.
2. Each turn is processed through a staged pipeline. Context building, tool planning, action execution and finalization are separate layers.
3. Tool calls are normalized into actions. Actions pass through planning, policy, approval, dispatch, result normalization, scanning, retry and audit.
4. Results become outputs. Output sources are planned into artifact records and summarized for response composition.
5. Final responses are metadata-backed. ResponseComposer creates a FinalResponse plan from runtime state, outputs, approvals and warnings.
6. Memory writing is plan-only. The current memory writer produces MemoryWritePlan and filters sensitive candidates; it does not persist to a database.
7. Observability is structured. TurnTrace and ObservabilityEvent are generated from metadata.
8. Truth and stability are runtime reports. Version, configuration and capability facts are reported by the truth layer, and StabilityGate checks required runtime outputs.

## Main pipeline

```text
UserInput
  -> SceneDecision
  -> RuntimeStateResolver
  -> TaskDetector
  -> TaskPlanner / WorkflowPlanner
  -> StepExecutor.prepare_current_step
  -> EvidencePipeline
  -> ToolPlannerV2
  -> PromptCompiler
  -> LLM tool calls
  -> ActionExecutionKernel
  -> StepExecutor.apply_action_results
  -> RuntimeStateTransition
  -> CompletionEvaluator
  -> ResultCollector
  -> ArtifactPlanner
  -> ArtifactWriter
  -> ArtifactRegistry
  -> OutputSummarizer
  -> ResponseComposer
  -> MemoryWritePlanner
  -> ObservabilityCollector
  -> TruthReporter
  -> StabilityGate
  -> RuntimeStateStore
  -> RuntimeStateSnapshotter
```

## Runtime state model

```text
RuntimeState
  -> SessionState
  -> WorkspaceState
  -> TaskState
  -> WorkflowState
  -> StepState
  -> ActionState
  -> ArtifactState
```

The active task and workflow guide continuation, cancellation, current step selection, output registration and final response generation.

## Finalization layer

The finalization layer runs after action execution. It writes these metadata keys:

```text
artifact_records
output_summary
final_response
memory_write_plan
turn_trace
truth_report
stability_report
```

The final snapshot is written after finalization so artifact and task updates are included in saved runtime state.

## Safety boundaries

- High-risk actions are handled by the action policy and approval gate.
- Tool results are normalized and scanned before reuse.
- Memory candidates are filtered before they can be accepted into a write plan.
- StabilityGate verifies the presence of required runtime outputs.

## Capability-first Execution Architecture

The runtime now uses a capability-first execution model.

Definitions:

- Skill: a CapabilityPackage-derived user-facing business entry.
- CapabilityPackage: internal business capability declaration.
- Business Module: domain implementation service. Current modules are config_translation, config_analysis, and pcap_analysis.
- Platform Service: infrastructure service such as workspace, knowledge, memory, artifact, runtime, report, and web.
- Tool: callable adapter. LLM-visible business tools are directory-level tools such as config.analysis.run and pcap.analysis.run.

See [docs/CAPABILITY_FIRST_ARCHITECTURE.md](docs/CAPABILITY_FIRST_ARCHITECTURE.md).
