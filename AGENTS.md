# Agent Runtime (v3.4)

## Turn Lifecycle

```
UserInput
  → TurnContext
  → SceneDecision
  → RuntimeState / TaskWorkflow
  → Context / Memory / Knowledge (EvidencePipeline)
  → ToolPlannerV2
  → PromptCompiler
  → LLM sampling
  → ActionPlanner → ActionExecutor (RiskPolicy → ApprovalGate → Dispatch)
  → ResultCollector → ArtifactPlanner → ArtifactWriter → ArtifactRegistry
  → OutputSummarizer
  → ResponseComposer
  → MemoryWritePlanner
  → ObservabilityCollector
  → TruthReporter
  → StabilityGate
  → RuntimeStateSnapshot
  → FinalResponse
```

## 13-Stage Context Pipeline

```
1. ContextInitStage       — create TurnContext
2. ModelConfigStage       — resolve LLM model config
3. HistoryStage           — load history window (k=30)
4. ToolRouterStage        — build base tool router
5. CapabilitySelectionStage — select capabilities, snapshot services
6. SceneDecisionStage     — compute scene decision
7. RetrievalPolicyStage   — evaluate retrieval triggers
8. RuntimeStateStage      — prepare runtime state hooks
9. EvidenceStage          — run EvidencePipeline → EvidenceBundle
10. ToolPlanningStage     — ToolPlannerV2: core tool selection
11. SafeContextStage       — build LLM-visible context + snapshot
12. LoadedCapabilityStage — inject capability contracts
13. MetadataWriteStage     — finalize metadata
```

## Tool Visibility

Tools flow through 4 filter layers before reaching LLM:

1. **Namespace filter** — only canonical tool_ids pass
2. **Model visible filter** — enabled + non-forbidden + callable_by_llm
3. **CORE_TOOL_IDS** (22 tools) — always injected regardless of planner output
4. **Scene-aware ToolPlannerV2** — activates remaining tools by scenario

Final: `model_visible ∩ (CORE_TOOL_IDS ∪ planner_candidates)` → 20-30 tools visible per turn.

## Capability Registry (v3.3+)

Capabilities define what the agent can do + safety contracts. No legacy "skills" concept.

| Capability | ID | Status | Safety |
|-----------|-----|--------|--------|
| Knowledge | knowledge | enabled | read only |
| Artifact Management | artifact_management | enabled | write (sandboxed) |
| Review Flow | review_flow | enabled | read |
| CMDB | cmdb | enabled | write (delete needs approval) |
| Network Device | network_device | enabled | real_device_access=true |
| PCAP Analysis | pcap_analysis | enabled | read |
| Coding | coding | enabled | commit/push needs approval |
| Browser | browser | enabled | read (external URLs) |
| Topology | topology | planned | — |
| Inspection | inspection | planned | — |

## Tool Execution

```
ActionPlanner → RiskPolicy → ApprovalGate → ToolDispatcher
  → ResultNormalizer → ResultScanner → ActionAuditTrail
```

Medium-risk tools (cmdb.add_asset, cmdb.delete_asset, git.commit, git.push) trigger approval gates.
High-risk tools (host.shell.exec, host.powershell.exec, host.python.exec) require manual approval.

## Session & Long-Task Support (v3.3)

- History window: 30 messages (was 8)
- Context compaction: 15 recent messages preserved + 25 key data fields
- Auto-checkpoint: every 5 turns (configurable)
- Exponential retry + circuit breaker (3 consecutive failures → 30s cooldown)
- Dynamic workflow steps (insert/remove/reorder mid-task)
- LLM tool planner enabled (refines deterministic seed via model)
- SSH session reuse (session_id for consecutive commands, sudo support)

## Sub-Agents

`agent.spawn` and `agent.team.run` support multi-agent collaboration.

## Metadata Keys

Each turn produces in `ctx.metadata`:

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
