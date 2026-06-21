# Capability-First Architecture

Capability-driven design from `capability_routing/` modules (v3.3.3).

## Execution Chain

```
ToolCall -> CapabilityRouter -> CapabilityPackage -> SkillManifest -> ToolBundle -> ToolPlannerV2 -> ToolExecutionPipeline
```

## Skill Definitions

- Skills are defined by `SkillManifest` — name, description, tags, tools list, metadata.
- `SKILL.md` files provide the prompt template body but are NOT embedded in manifests.
- Skills are discovered from `skills/` directories and grouped by category.

## Capability Packages

Defined in `agent/runtime/capability_routing/manifests.py`:

| Capability | Tools |
|-----------|-------|
| `workspace_read` | workspace.file.list, workspace.file.read, workspace.file.preview, workspace.artifact.read |
| `knowledge_qa` | knowledge.search, knowledge.chunk.read, knowledge.source.read |
| `memory_lookup` | memory.search, memory.list, memory.profile.get |
| `config_translation` | workspace.file.list, workspace.file.read, config.analysis.run |
| `pcap_analysis` | workspace.file.list, pcap.analysis.run |
| `report_drafting` | report.markdown.render, report.artifact.save, workspace.artifact.save |
| `runtime_diagnostics` | runtime.health, runtime.diagnostics, runtime.selfcheck |

## CORE_TOOL_IDS (always available)

18 tools in `manifests.py CORE_TOOL_IDS`:

```
skill.search, skill.load, workspace.file.list, workspace.file.read,
workspace.artifact.read, tool.catalog.search,
host.shell.exec, host.powershell.exec, host.python.exec,
host.command.slash_run,
web.search, web.docs.official_search, web.page.summarize,
web.page.extract_links, web.page.save_artifact,
web.news.search, web.weather.current, web.weather.forecast
```

## Module Manifests

`capability_routing/manifests.py MODULE_MANIFESTS` defines 8 modules:

| Module ID | Kind | Handler |
|-----------|------|---------|
| workspace | platform | agent.modules.workspace |
| knowledge | platform | agent.modules.knowledge |
| memory | platform | agent.modules.memory |
| config_translation | business | agent.modules.config_translation |
| config_analysis | business | agent.modules.config_analysis |
| pcap_analysis | business | agent.modules.pcap |
| report | platform | agent.modules.report |
| runtime | platform | agent.modules.runtime |

Additional module directories exist under `agent/modules/` (artifact, cmdb, inspection, review, topology) for future expansion.

## ToolPlannerV2

- Located in `agent/runtime/tool_planning/planner.py`
- Default tool_limit: 12
- Does NOT default to full TOOL_NAMESPACE — narrows by capability routing
- Produces `ToolPlanningDecision` and `ToolPlanningPolicy`

## Invariants

- SkillManifest contains no prompt body.
- CapabilityPackage is the source of built-in skills.
- Platform services are not business modules.
- Directory-level business tools: config.analysis.run, pcap.analysis.run.
- Prompt does not include full tool catalog.
- Prompt does not include skill_prompt.
- ToolPlannerV2 does not default to list(TOOL_NAMESPACE).
