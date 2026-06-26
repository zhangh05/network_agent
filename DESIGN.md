# Current Runtime Design (v3.8)

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
  → TaskDetector (new_task / continue / cancel, expanded v3.8 verbs)
  → TaskPlanner → WorkflowPlanner (dynamic steps v3.8)
  → StepExecutor.prepare_current_step
  → EvidencePipeline (Context + Memory + Knowledge layers)
  → ToolPlannerV2 (deterministic seed + LLM refinement v3.8)
  → PromptCompiler
  → LLM tool calls (Max 8 step loops per turn, configurable)
  → ToolExecutionPipeline
      → ActionPlanner → RiskPolicy → ApprovalGate → Dispatch
      → CircuitBreaker (v3.8) + Exponential Retry (v3.8)
  → StepExecutor.apply_action_results
  → RuntimeStateTransition
  → CompletionEvaluator
  → ResultCollector → ArtifactPlanner → ArtifactWriter → ArtifactRegistry
  → OutputSummarizer → ResponseComposer
  → MemoryWritePlanner (extract + filter + dedupe + write, max 3/turn)
  → Auto-Checkpoint Guard (v3.8, every 5 turns)
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
  ├── WorkflowState (ordered StepState list, dynamic insert/remove v3.8)
  ├── StepState (pending/running/completed/failed/blocked/approval_pending/skipped)
  ├── ActionState (planned/executing/completed/failed/blocked)
  └── ArtifactState (registered/exported/deleted)
```

## Tool System Architecture (v3.8)

```
CanonicalRegistry (73 tools, single truth source)
  ↓
Namespace filter (tool_namespace_data.py, 13 categories)
  ↓
Capability routing (keyword-based + semantic fallback)
  ↓
Core tools (16) + capability-matched → max ~24 visible to LLM
```

### Tool Categories (13)

| Category | Count | Tools |
|----------|-------|-------|
| exec | 3 | exec.run, exec.python, exec.slash |
| device | 4 | device.add, device.get, device.list, device.delete |
| workspace | 17 | workspace.file.*, workspace.artifact.* |
| knowledge | 8 | knowledge.search, knowledge.import, knowledge.* |
| web | 3 | web.search, web.page.process, web.weather |
| system | 9 | system.diagnostics, system.session.*, system.review.* |
| memory | 3 | memory.manage, memory.profile, memory.search |
| data | 9 | data.*, text.analyze, report.* |
| agent | 5 | agent.spawn, agent.team.run, tool.catalog.search |
| git | 5 | git.status, git.diff, git.log, git.commit, git.push |
| code | 1 | code.search |
| config | 2 | config.analysis.run, pcap.analysis.run |
| browser | 4 | browser.navigate, browser.extract, browser.screenshot, browser.click |

## Capability-first Architecture (v3.8)

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

No legacy "skill" concept since v3.8. Replaced by:
- **Capability** = what the agent can do (safety contract)
- **Skill (SKILL.md)** = reusable workflow recipe (v3.8, agentskills.io standard)

## Safety Boundaries

- High-risk actions (`exec.run`, `exec.python`, `exec.slash`) → approval gate
- Medium-risk actions (`device.add`, `device.delete`, `git.commit`, `git.push`) → approval gate
- Dangerous commands (`reload`, `reboot`, `reset`, `format`, `rm -rf`, `dd if=`, `mkfs`) → blocked
- SSH/Telnet session reuse → same-session commands skip repeat authentication
- Memory candidates filtered before write plan (risk + dedupe + count cap)
- StabilityGate verifies required runtime outputs presence
