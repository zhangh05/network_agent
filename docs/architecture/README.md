# Architecture Notes

This folder contains current architecture notes only. The authoritative runtime chain is:

```text
AgentApp -> TurnRunner -> ToolExecutionPipeline -> ToolRuntimeClient -> ToolExecutor
```

Current anchors:

- `../../DESIGN.md` — full current design.
- `../ARCHITECTURE.md` — short architecture reference.
- `../../tool_runtime/tool_namespace.py` — public tool namespace.
- `../../tool_runtime/manifest_registry.py` — tool manifests.
- `../../agent/capabilities/catalog.py` — business capability catalog.

Do not add documents for removed compatibility paths or old tool names.
