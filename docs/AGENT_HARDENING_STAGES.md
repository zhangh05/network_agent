# Agent Hardening Stages

This document records the integrated hardening scope for runtime flow, context/memory boundaries, and tool governance.

## Stage 1 — Runtime flow and transport contract

Implemented in this branch:

- `AgentApp` protects the session map with a lock.
- Implicit sessions now use UUID-based ids instead of `session_{len(self._sessions)}`.
- Turns for the same session are serialized with a per-session turn lock.
- Different sessions can still run concurrently.
- HTTP `stream=true` is explicitly marked as `event_replay`, not true live streaming.
- WebSocket execution continues to use the shared `AgentApp.submit_user_message()` contract.
- WebSocket `StreamEmitter` callback is set inside the worker thread, where thread-local callbacks actually apply.

## Stage 2 — Context, memory, and observability contract

Partially implemented / contract established in this branch:

- Transport and stream mode are attached to turn metadata.
- Tool visibility metadata is produced by the planner: scene, reason, visible tools, local-ops status, baseline tools, and filtered tools.
- Unknown tools fail closed in the deterministic planner.
- Local execution tools are not part of the universal baseline.

Follow-up implementation target:

- Split `context_builder.py` into history, tool visibility, RAG/memory, compaction, and runtime snapshot helpers without changing external behavior.
- Surface RAG/memory blocked/summarized/compact decisions in the Inspector trace.
- Add atomic-write and redaction consistency checks for message/context/run stores.

## Stage 3 — Tool governance and productization

Implemented in this branch:

- Shell / PowerShell / Python execution remains supported.
- These tools are visible only for local operations, diagnostics, or explicit command-execution intent.
- Simple chat, knowledge QA, translation, report, and offline file-analysis scenes no longer inherit execution tools from baseline injection.
- Sub-agent coordination tools are no longer universal; they are exposed only for complex / parallel / delegated task scenes.

Follow-up implementation target:

- Add harness cases for simple chat, knowledge QA, local command execution, approval rejection, approval success, and same-session concurrency.
- Add an Agent decision panel showing scene, selected skills, candidate tools, visible tools, RAG/memory hits, approval status, and no-tool/tool-decision reasons.
- Unify version source across `VERSION`, `/api/version`, README, and release notes.

## Acceptance checks

Expected behavior after this branch:

- Simple chat should not expose `host.shell.exec`, `host.powershell.exec`, or `host.python.exec`.
- Knowledge QA should expose read/search tools, not local execution tools.
- Explicit requests such as “执行本机命令 / 查看本机端口 / run PowerShell” may expose local execution tools and still require approval at execution time.
- Same-session concurrent turns should serialize instead of interleaving session history and tool results.
- HTTP SSE responses should identify themselves as `event_replay`.
- WebSocket responses should identify themselves as `live` when live events are emitted, or `event_replay_fallback` otherwise.
