# Runtime Reference

Runtime execution model (v3.8).

## Turn Flow

```
POST /api/agent/message
  -> ContextPipeline (13 stages, builds TurnContext)
  -> TurnRunner: LLM ↔ ToolExecutionPipeline loop (max 8 steps)
  -> ResultBuilder (build AgentResult)
  -> Post-turn Hooks (output, memory, observability, truth, stability)
  -> FinalResponse
```

## ContextPipeline (13 stages)

1. **ContextInitStage** — create initial TurnContext
2. **ModelConfigStage** — configure model parameters
3. **HistoryStage** — load conversation history (k=30)
4. **ToolRouterStage** — route to relevant tool categories
5. **CapabilitySelectionStage** — select enabled capabilities
6. **SceneDecisionStage** — classify user intent
7. **RetrievalPolicyStage** — decide retrieval strategy
8. **RuntimeStateStage** — initialize runtime state / task workflow hooks
9. **EvidenceStage** — build evidence bundle (context + memory + knowledge)
10. **ToolPlanningStage** — ToolPlannerV2: deterministic seed + LLM refine (v3.8)
11. **SafeContextStage** — build safe/scrubbed context + runtime snapshot
12. **LoadedCapabilityStage** — inject capability contracts
13. **MetadataWriteStage** — write context metadata

## Tool Execution

Tools are dispatched via `ToolInvocation` through the canonical registry.
Each call goes through: RiskPolicy → ApprovalGate → Dispatch → ResultNormalizer.

SSH/Telnet tools use `exec.run` (target=ssh / target=telnet) with persistent session reuse (session_id).
Dangerous commands (reload, reboot, reset, format, rm -rf, dd if=, mkfs) are blocked.

## Post-turn Hooks

| Hook | Purpose |
|------|---------|
| Output Hooks | Artifact planning, writing, registration |
| Memory Hooks | Memory candidate extraction, filtering, write |
| Observability Hooks | TurnTrace generation |
| Truth Hooks | Version, config, capability reporting |
| Stability Hooks | Required output presence verification |

Executed by `hook_runner.py` after TurnRunner completes:

| Hook | Module | Writes to ctx.metadata |
|------|--------|----------------------|
| Output collection | `output/collector.py` | `output_summary`, `artifact_records` |
| Response composition | `response/renderer.py` | `final_response` |
| Memory write planning | `memory_write/planner.py` | `memory_write_plan` |
| Observability collection | `observability/collector.py` | `turn_trace` |
| Truth reporting | `truth/report.py` | `truth_report` |
| Stability gate | `stability/gate.py` | `stability_report` |

## API Response Metadata

`AgentResult.to_dict()` propagates these metadata keys via `enrich_metadata()`:

```
selected_skills, visible_tools, dynamic_tool_expansions,
memory_hits_count, knowledge_hits_count, context_sources,
source_summary, source_count, citations, retrieval_diagnostics
```

The following keys exist in `ctx.metadata` but are NOT propagated to the API response:

```
runtime_state_snapshot, task_signal, action_trace, artifact_records,
output_summary, memory_write_plan, turn_trace, truth_report, stability_report
```

## Entry Points

| API | Purpose |
|-----|---------|
| `POST /api/agent/message` | Main agent entry (sync) |
| `WS /ws/agent` | WebSocket real-time streaming |
| `GET /api/runtime/health` | Component health check |
| `GET /api/runtime/selfcheck` | System self-check |
| `GET /api/agent/usage` | Token/cost usage stats |
