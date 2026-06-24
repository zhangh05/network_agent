# Current Runtime Design (v3.4)

This document describes the current source architecture only.

## Principles

1. **Runtime state is explicit.** Session, workspace, task, workflow, step, action and artifact state are first-class runtime objects.
2. **Each turn is a staged pipeline.** Context building, tool planning, action execution and finalization are separate layers in a 13-stage pipeline.
3. **Tools are canonical.** All tools registered in `tool_runtime/canonical_registry.py` with handler + input_schema + risk_level. Capability tools reference canonical handlers — never override schemas.
4. **Actions wrap tools.** Tool calls pass through ActionPlan → RiskPolicy → ApprovalGate → dispatch → result normalization → audit.
5. **Results become outputs.** Output sources are planned into artifact records and summarized for response composition.
6. **Final responses are metadata-backed.** ResponseComposer creates a FinalResponse plan from runtime state, outputs, approvals and warnings.
7. **Memory writes are plan-first.** MemoryWritePlanner extracts candidates, filters by risk, deduplicates, then writes up to 3 records per turn to ContextStore (JSONL).
8. **Observability is structured.** TurnTrace and ObservabilityEvent are generated from metadata.
9. **Truth and stability are runtime reports.** Version, configuration and capability facts are reported by the truth layer, and StabilityGate checks required runtime outputs.

## Main Pipeline

```text
UserInput
  → 13-Stage Context Pipeline
  → SceneDecision
  → RuntimeStateResolver
  → TaskDetector (new_task / continue / cancel, expanded v3.3 verbs)
  → TaskPlanner → WorkflowPlanner (dynamic steps v3.3)
  → StepExecutor.prepare_current_step
  → EvidencePipeline (Context + Memory + Knowledge layers)
  → ToolPlannerV2 (deterministic seed + LLM refinement v3.3)
  → PromptCompiler
  → LLM tool calls (Max 8 step loops per turn, configurable)
  → ToolExecutionPipeline
      → ActionPlanner → RiskPolicy → ApprovalGate → Dispatch
      → CircuitBreaker (v3.3) + Exponential Retry (v3.3)
  → StepExecutor.apply_action_results
  → RuntimeStateTransition
  → CompletionEvaluator
  → ResultCollector → ArtifactPlanner → ArtifactWriter → ArtifactRegistry
  → OutputSummarizer → ResponseComposer
  → MemoryWritePlanner (extract + filter + dedupe + write, max 3/turn)
  → Auto-Checkpoint Guard (v3.3, every 5 turns)
  → ObservabilityCollector
  → TruthReporter
  → StabilityGate
  → RuntimeStateStore
  → RuntimeStateSnapshotter
```

## Runtime State Model

```text
RuntimeState
  ├── SessionState (session_id, workspace_id, turn_count)
  ├── WorkspaceState (memory_gating, artifact_policy)
  ├── TaskState (pending/running/completed/failed/blocked/approval_pending)
  ├── WorkflowState (ordered StepState list, dynamic insert/remove v3.3)
  ├── StepState (pending/running/completed/failed/blocked/approval_pending/skipped)
  ├── ActionState (planned/executing/completed/failed/blocked)
  └── ArtifactState (registered/exported/deleted)
```

## Tool System Architecture (v3.4)

```
CanonicalRegistry (102 tools, single truth source)
  ↓ to_tool_specs() — skips forbidden entries
  ↓
Namespace filter (tool_namespace_data.py, 13 categories)
  ↓
CapabilityRegistry filter (10 manifests, 8 enabled)
  ↓
Model visible filter (enabled + callable_by_llm + non-forbidden)
  ↓
ToolPlannerV2 (deterministic + LLM refine) → CORE_TOOL_IDS union
  ↓
Final: 20-30 tools visible to LLM per turn
```

### Tool Categories (13)

| Category | Tools | Examples |
|----------|-------|----------|
| host | 4 | shell.exec, powershell.exec, python.exec, slash_run |
| workspace | 23 | file.*, artifact.*, metadata.get |
| knowledge | 12 | search, chunk.*, source.*, import |
| network | 4 | ssh, telnet, config.analysis.run, pcap.analysis.run |
| web | 7 | search, docs, page.*, news, weather |
| runtime | 13 | health, diagnostics, run.*, session.* |
| memory | 8 | search, create, confirm, profile.* |
| report_data | 13 | report.*, data.*, text.*, diagram.* |
| agent | 6 | role.list, spawn, team.run, tool.catalog.search |
| cmdb | 4 | list_assets, get_asset, add_asset, delete_asset |
| git | 5 | status, diff, log, commit, push |
| code | 1 | search |
| browser | 2 | navigate, extract |

## Capability-first Architecture (v3.4)

Capabilities are safety-tagged agent abilities. Each capability declares tools + risk levels + safety contracts.

```text
CapabilityManifest
  ├── capability_id (e.g. "coding", "network_device")
  ├── status (enabled / planned / disabled)
  ├── intent_patterns (trigger keywords)
  ├── prompt_summary (LLM context injection)
  ├── module (CapabilityModuleSpec)
  ├── tools (CapabilityToolRef[] — references canonical handlers)
  ├── outputs (CapabilityOutputSpec[])
  └── safety (CapabilitySafetySpec — real_device_access, config_push, human_review)
```

No legacy "skill" concept since v3.3. Replaced by:
- **Capability** = what the agent can do (safety contract)
- **Skill (SKILL.md)** = reusable workflow recipe (v3.4, agentskills.io standard)

## Safety Boundaries

- High-risk actions (`host.shell.exec`, `host.powershell.exec`, `host.python.exec`) → approval gate
- Medium-risk actions (`cmdb.add_asset`, `cmdb.delete_asset`, `git.commit`, `git.push`) → approval gate
- Dangerous commands (`reload`, `reboot`, `reset`, `format`, `rm -rf`, `dd if=`, `mkfs`) → blocked
- SSH/Telnet session reuse → same-session commands skip repeat authentication
- Memory candidates filtered before write plan (risk + dedupe + count cap)
- StabilityGate verifies required runtime outputs presence
