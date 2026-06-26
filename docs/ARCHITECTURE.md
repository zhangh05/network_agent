# Architecture

Current source architecture reference (v3.9).

## Turn Pipeline

```
UserInput -> ContextPipeline (13 stages) -> TurnRunner -> ToolExecutionPipeline -> ResultBuilder -> HookRunner -> AgentResult
```

### ContextPipeline Stages (`agent/runtime/context_pipeline/`)
1. ContextInitStage → ModelConfigStage → HistoryStage → ToolRouterStage → CapabilitySelectionStage
2. SceneDecisionStage → RetrievalPolicyStage → RuntimeStateStage → EvidenceStage
3. ToolPlanningStage → SafeContextStage → LoadedCapabilityStage → MetadataWriteStage

### TurnRunner (`agent/runtime/runner.py`)
4 execution stages: ContextStage → MessageStage → ModelStage → PersistenceStage, with embedded LLM tool-call loop.

### ToolExecutionPipeline (`agent/runtime/tool_execution/pipeline.py`)
9 stages: ApprovalStage → CatalogStage → RiskStage → PermissionStage → DispatchStage → UnknownToolStage → ResultStage → OutputPolicy → RetryPolicy.

## Main Packages

### Runtime Sub-modules (`agent/runtime/`)
| Module | Purpose |
|--------|---------|
| `cognition/` | Scene decision, evidence bundle, prompt compiler |
| `state/` | RuntimeState, TaskState, WorkflowState, StepState |
| `tasking/` | TaskDetector, Planner, StepExecutor, Completion |
| `tool_execution/` | ToolExecutionPipeline with 9 stages |
| `tool_planning/` | ToolPlannerV2, ToolPlanningPolicy, ToolPlanningDecision |
| `capability_routing/` | CapabilityRouter, manifests, models, toolset, evaluation |
| `context_pipeline/` | 13-stage ContextPipeline, stages, models |
| `prompt_architecture/` | Prompt building architecture |
| `prompting/` | Prompt templates |
| `context/` | ContextFrame, QueryPlan, Resolver |
| `memory/` | MemoryRetriever, ReadPolicy, WritePolicy |
| `memory_write/` | Memory candidate extraction, filtering, dedup |
| `knowledge/` | KnowledgeRetrieverV2, Reranker, CitationGraph |
| `actions/` | ActionPlan, RiskPolicy, ApprovalGate, ActionExecutor |
| `output/` | Output collection, planning, writing, registry, summarization |
| `response/` | Response strategy, composition, rendering |
| `observability/` | Event collection, TurnTrace export |
| `truth/` | Version, config, capability single source of truth |
| `stability/` | Stability gate: metadata, stage, compat checks |
| `stages/` | TurnRunner stages: context, messages, model, persistence |
| `decision_report/` | Per-turn decision report generation |
| `retrieval/` | RetrievalTriggerPolicy, UnknownFeedback |

### Top-level modules
| Package | Purpose |
|---------|---------|
| `agent/` | Core agent loop, LLM provider, app service |
| `artifacts/` | ArtifactRecord, save/store/retrieve, run artifact index |
| `backend/` | Flask API (50+ endpoints), WebSocket, contracts |
| `context/` | ContextStore (JSONL), schema registry, migration |
| `frontend/` | React/TS + Vite, 10 nav items, 12 pages |
| `jobs/` | JobRecord, JobEvent, store, manager, worker, redaction |
| `memory/` | Memory store adapter, writer, retriever, conflicts |
| `storage/` | FileStore, reference index, paths |
| `tool_runtime/` | ToolInvocation, canonical registry, capability actions |
| `workspace/` | Workspace manager, session store, IDs |

## Key ctx.metadata Keys

```
runtime_state_snapshot, task_signal, action_trace,
artifact_records, output_summary, final_response,
memory_write_plan, turn_trace, truth_report, stability_report
```

Note: Not all metadata keys are propagated to API responses. `enrich_metadata()` selectively copies context metadata to `AgentResult.metadata`.

## Tech Stack

- Backend: Flask + Python 3.12+, port 8010
- Frontend: React/TS + Vite, port 5173
- LLM: MiniMax M3 (245K context window)
- Retrieval: BM25 + CJK bigram/trigram
- Storage: JSONL (append-write + tombstone delete + compact GC)
