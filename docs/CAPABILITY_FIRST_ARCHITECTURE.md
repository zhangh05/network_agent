# Capability-First Architecture (v3.4)

Capability-driven design: capabilities define what the agent can do with safety contracts. Tool visibility is scene-aware.

## Architecture Layers

```
CapabilityRegistry (10 manifests: 8 enabled + 2 planned)
  → declares: tools + intent_patterns + safety contracts + prompt_summary
  ↓
ToolPlannerV2 (deterministic seed + optional LLM refinement)
  → outputs: candidate tools per scene
  ↓
CORE_TOOL_IDS (22 always-visible baseline tools)
  → union with planner output = final visible tools
  ↓
LLM receives: 20-30 tools per turn (not full 102)
  → calls tools → ActionPlanner → RiskPolicy → ApprovalGate → dispatch
```

## Capabilities

Defined in `agent/capabilities/builtin.py` and `agent/modules/*/capability.py`:

| Capability | ID | Status | Safety Notes |
|-----------|-----|--------|--------------|
| Knowledge / RAG | knowledge | enabled | Search + retrieve + import |
| Artifact Management | artifact_management | enabled | Save + read + export artifacts |
| Review Flow | review_flow | enabled | Manual review items |
| CMDB | cmdb | enabled | Asset CRUD; delete needs approval |
| Network Device | network_device | enabled | `real_device_access=true`; SSH/Telnet with session reuse |
| PCAP Analysis | pcap_analysis | enabled | Parse + session + filter + align |
| Coding | coding | enabled | Git operations; commit/push needs approval |
| Browser | browser | enabled | Navigate + extract; external URLs only |
| Topology | topology | planned | Reserved for auto-discovery |
| Inspection | inspection | planned | Reserved for config audit |

## CORE_TOOL_IDS (v3.4 — 22 tools)

```text
tool.catalog.search, workspace.file.list, workspace.file.read,
workspace.artifact.read,
host.shell.exec, host.powershell.exec, host.python.exec,
host.command.slash_run,
web.search, web.docs.official_search, web.page.summarize,
web.page.extract_links, web.page.save_artifact,
web.news.search, web.weather,
cmdb.list_assets, cmdb.get_asset, cmdb.add_asset, cmdb.delete_asset,
network.ssh, network.telnet,
git.status, git.diff, git.log,
code.search
```

CORE_TOOL_IDS are **unconditionally injected** into every turn. Remaining tools activated by ToolPlannerV2 scene detection.

## CapabilityPackage Routing

Defined in `agent/runtime/capability_routing/manifests.py`:

| Package | Priority | Tools |
|---------|----------|-------|
| workspace_read | 10 | workspace.file.* |
| knowledge_qa | 20 | knowledge.* |
| memory_lookup | 30 | memory.* |
| config_translation | 5 | config.analysis.run + workspace.file.* |
| pcap_analysis | 6 | pcap.analysis.run + workspace.file.* |
| report_drafting | 40 | report.* + workspace.artifact.* |
| runtime_diagnostics | 50 | runtime.health, runtime.diagnostics |
| cmdb | 7 | cmdb.* |
| network_device | 6 | network.ssh, network.telnet |

## ToolPlannerV2

- Located in `agent/runtime/tool_planning/planner.py`
- `MAX_CANDIDATE_TOOLS = 30`
- Deterministic seed via keyword-based SIGNAL_DISPATCH
- LLM refinement enabled (v3.3) — refines seed via model when available
- Does NOT default to full namespace — narrows by scene + capability routing
- Produces `ToolPlanningDecision` and `ToolPlanningPolicy`

## Tool Categories (13 total, in `tool_namespace_data.py`)

```
host(4)  workspace(23)  knowledge(12)  network(4)  web(7)
runtime(13)  memory(8)  report_data(13)  agent(6)  cmdb(4)
git(5)  code(1)  browser(2)
```

## Invariants

- CapabilityManifest contains no skills field (removed v3.3).
- CapabilityToolRef references canonical handlers — never overrides schemas.
- CORE_TOOL_IDS are always visible regardless of planner output.
- LLM never sees full 102-tool catalog (max ~30 per turn).
- SSH/Telnet sessions support reuse via session_id (v3.3).
- Dangerous commands (reload/reboot/reset/format/rm -rf/dd if=/mkfs) blocked.
