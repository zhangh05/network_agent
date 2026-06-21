# Runtime Reference

Runtime execution model (v3.3.3).

## Turn Flow

```
POST /api/agent/message
  -> ContextPipeline (13 stages, builds TurnContext)
    -> TurnRunner.run()
      -> ContextStage (runtime state init)
      -> MessageStage (build LLM messages)
      -> ModelStage (LLM call with tool-call loop)
      -> ToolExecutionPipeline (9 stages)
      -> PersistenceStage (save run, trace, decision)
  -> ResultBuilder (build AgentResult)
  -> HookRunner (post-turn hooks: output, memory, observability, truth, stability)
  -> AgentResult.to_dict()
```

## ContextPipeline (13 stages)

`agent/runtime/context_pipeline/pipeline.py`

1. **ContextInitStage** — create initial context
2. **ModelConfigStage** — configure model parameters
3. **HistoryStage** — load conversation history
4. **ToolRouterStage** — route to relevant tool categories
5. **SkillSelectionStage** — select applicable skills
6. **SceneDecisionStage** — classify user intent
7. **RetrievalPolicyStage** — decide retrieval strategy
8. **RuntimeStateStage** — initialize runtime state
9. **EvidenceStage** — build evidence bundle (context + memory + knowledge)
10. **ToolPlanningStage** — plan tool usage (ToolPlannerV2)
11. **SafeContextStage** — build safe/scrubbed context
12. **LoadedSkillStage** — load skill manifests
13. **MetadataWriteStage** — write context metadata

## ToolExecutionPipeline (9 stages)

`agent/runtime/tool_execution/pipeline.py`

1. **ApprovalStage** — check if approval required
2. **CatalogStage** — search tool catalog
3. **RiskStage** — assess tool risk level
4. **PermissionStage** — check tool permissions
5. **DispatchStage** — dispatch to tool handler
6. **UnknownToolStage** — handle unknown tool errors
7. **ResultStage** — process tool result
8. **OutputPolicy** — apply output policies
9. **RetryPolicy** — retry on failure

## Post-turn Hooks

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
