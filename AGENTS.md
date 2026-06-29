# AGENTS.md

This file is the handoff contract for AI coding agents working in this repository.

## Non-Negotiable Rules

1. Keep the current architecture only. Do not add compatibility branches, old tool names, fallback APIs, or historical docs.
2. All tool calls must go through `ToolRuntimeClient.invoke()`.
3. All tools must be one of the 21 canonical IDs in `tool_runtime/tool_namespace.py`.
4. `workspace_id` must be explicit and validated at API boundaries. Empty values return 400.
5. Approval is for high-risk/destructive actions, not for ordinary read/list/query operations.
6. Memory writes go through `workspace.memory_governance.MemoryWriteGate`.
7. Do not commit runtime data, provider secrets, logs, build output, caches, or workspace contents.

## Current Main Chain

```text
Frontend
  -> backend/main.py routes or backend/ws/agent_ws.py
  -> agent.app.facade.AgentApp
  -> AgentThread / TurnRunner
  -> context + prompt pipeline
  -> LLM provider
  -> ToolExecutionPipeline
  -> ToolRuntimeClient
  -> ToolExecutor
  -> durable state, messages, artifacts, memory, trace
```

## Canonical Tools

There are exactly 21 public tool IDs:

`agent.manage`, `browser.manage`, `code.search`, `config.manage`, `data.manage`, `device.manage`, `exec.run`, `git.manage`, `knowledge.manage`, `memory.manage`, `pcap.manage`, `report.manage`, `skill.manage`, `system.manage`, `text.analyze`, `web.manage`, `workspace.artifact`, `workspace.document.pdf.extract_text`, `workspace.file`, `workspace.filestore`, `workspace.metadata.get`

If a change needs a new operation, add it behind an existing canonical tool unless there is a strong product reason to create a new public tool.

## Review Checklist

Before committing:

- Search for old tool IDs and direct handler dispatch.
- Confirm `TOOL_NAMESPACE`, manifests, and registry counts match.
- Run focused tests for the changed layer.
- Run frontend typecheck for frontend/API contract edits.
- Inspect `git status --short` and stage only intended source/docs/tests.

Useful commands:

```bash
python3 - <<'PY'
from tool_runtime.tool_namespace import TOOL_NAMESPACE
from tool_runtime.manifest_registry import MANIFESTS
from tool_runtime.registry import get_default_registry
print(len(TOOL_NAMESPACE), len(MANIFESTS), get_default_registry().count())
PY

python3 -m pytest harness/test_business_capability_catalog.py harness/test_v394_no_legacy_tool_ids.py -q
npm --prefix frontend run typecheck
```

## Local Cleanup

Safe cleanup targets:

- `.DS_Store`
- `__pycache__/`
- `.pytest_cache/`
- frontend build output
- generated audit reports

Preserve:

- `workspaces/default/`
- `workspaces/_runtime/`
- `config/providers/`
- `config/llm.local.yaml`
- running backend/frontend processes unless the user asks to restart
