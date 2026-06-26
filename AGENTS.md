# Agent Runtime (v3.8)

## Turn Lifecycle

```
UserInput
  → TurnContext
  → SceneDecision
  → RuntimeState
  → Context / Memory / Knowledge
  → CapabilityRouter (semantic + keyword)
  → ToolPlannerV2
  → PromptCompiler
  → LLM sampling
  → ToolExecutionPipeline (RiskPolicy → ApprovalGate → Dispatch → Retry)
  → ArtifactWrite → OutputSummarize
  → MemoryWritePlanner
  → ObservabilityCollector
  → FinalResponse
```

## Context Pipeline

1. ContextInitStage       — create TurnContext
2. ModelConfigStage       — resolve LLM model config
3. HistoryStage           — load history window (k=30)
4. ToolRouterStage        — build active tool bundle
5. CapabilitySelectionStage — select capabilities, snapshot services
6. SceneDecisionStage     — compute scene decision
7. RetrievalPolicyStage   — evaluate retrieval triggers
8. RuntimeStateStage      — prepare runtime state hooks
9. EvidenceStage          — run EvidencePipeline → EvidenceBundle
10. ToolPlanningStage     — ToolPlannerV2: core tool selection
11. SafeContextStage       — build LLM-visible context + snapshot
12. LoadedCapabilityStage — inject capability contracts
13. MetadataWriteStage     — finalize metadata

## Tool Visibility

Tools flow through 3 filter layers before reaching LLM:

1. **Canonical filter** — only 73 canonical tool_ids pass
2. **Capability routing** — selects domains by user intent (keyword + semantic)
3. **Core tools** (16 tools) — always visible regardless of capability match

Final: `core_tools ∪ capability_matched` → max ~24 tools visible per turn.

### Core Tools (16)

exec.run, exec.python, exec.slash, workspace.file.list, workspace.file.read,
workspace.artifact.list, workspace.artifact.read, web.search, web.weather,
git.status, git.log, git.diff, code.search, system.diagnostics,
tool.catalog.search, device.list

## Tool Execution

```
ToolExecutionPipeline:
  risk → approval → dispatch → normalize → scan → retry → audit → evidence
```

- Medium-risk tools (`device.add`, `device.delete`, `git.commit`, `git.push`) require approval.
- High-risk tools (`exec.run`, `exec.python`, `exec.slash`) require manual approval.
- Dangerous commands (`reload`, `reboot`, `reset`, `rm -rf`, `format`) are blocked.
- Auto-retry: 3 attempts with exponential backoff on transient errors.

## Capability Routing (v3.8)

12 capability domains with keyword-based matching + semantic embedding fallback:

| Domain | Matches | Tools |
|--------|---------|-------|
| exec | 运行,ssh,telnet,cmd | exec.* |
| device | cmdb,设备,device | device.* |
| workspace | 文件,编辑,save | workspace.* |
| knowledge | 知识,文档,docs | knowledge.* |
| web | 搜索,browser,weather | web.* |
| memory | 记忆,remember | memory.* |
| git | commit,push,diff | git.* |
| code | 代码,search | code.* |
| config | 配置,analysis | config.* |
| data | csv,table,report | data.* |
| system | 审计,checkpoint | system.* |
| agent | team,spawn | agent.* |

## Agent Modes

- **TurnRunner**: Legacy while-loop (step < 8), used by default.
- **GraphRunner**: LangGraph StateGraph with checkpoint support. Enable via `AGENT_RUNTIME=langgraph`.

## Dynamic Breakpoints

- `AGENT_BREAKPOINT_TOOLS` env var pauses execution before specified tools.
- UI management via Inspector panel (`/api/agent/breakpoints`).

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
