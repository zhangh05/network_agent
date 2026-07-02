# Architecture Notes

This folder contains current architecture notes only. The authoritative runtime chain is:

```text
AgentApp -> SSOTRuntimeEngine -> ToolRuntimeClient -> ToolExecutor
```

Current anchors:

- `../../DESIGN.md` — full current design.
- `../ARCHITECTURE.md` — short architecture reference.
- `../../core/tools/tool_namespace.py` — public tool namespace.
- `../../core/tools/manifest_registry.py` — tool manifests.
- `../../agent/capabilities/catalog.py` — business capability catalog.

Do not add documents for removed compatibility paths or old tool names.
