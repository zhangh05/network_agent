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
- Harness coverage includes same-session turn serialization without invoking a real LLM provider.

## Stage 2 — Context, memory, and observability contract

Implemented in this branch:

- `context_builder.py` has been converted from a large all-in-one function into an orchestration pipeline.
- `agent/runtime/context_history.py` owns initial history-window extraction and durable SessionMessageStore hydration helpers.
- `agent/runtime/context_tools.py` owns follow-up detection, scene routing, deterministic planning, and per-turn visible-tool allowlists.
- `agent/runtime/cognition/` owns scene decision, evidence pipeline, and prompt compilation (replaced the former context_safe and context_compaction modules).
- Transport and stream mode are attached to turn metadata.
- Tool visibility metadata is produced by the planner: scene, reason, visible tools, local-ops status, baseline tools, and filtered tools.
- Unknown tools fail closed in the deterministic planner.
- Local execution tools are not part of the universal baseline.
- `SessionMessageStore` now redacts large content before artifact storage and uses unique tmp files + `os.replace` for atomic writes.

Follow-up implementation target:

- Move turn history hydration to `context_history.hydrate_history_from_store()` when doing the next loop-stage refactor.
- Add context/run store hardening where those stores still use fixed temp files or swallow persistence failures.
- Surface scan/compaction metadata in the frontend Inspector decision panel.

## Stage 3 — Tool governance and productization

Implemented in this branch:

- Shell / PowerShell / Python execution remains supported.
- These tools are visible only for local operations, diagnostics, or explicit command-execution intent.
- Simple chat, knowledge QA, translation, report, and offline file-analysis scenes no longer inherit execution tools from baseline injection.
- Sub-agent coordination tools are no longer universal; they are exposed only for complex / parallel / delegated task scenes.
- Harness coverage checks simple chat, knowledge QA, config translation, explicit local ops, sub-agent scene exposure, unknown-tool fail-closed behavior, and same-session serialization.

Follow-up implementation target:

- Add approval success/rejection harness around the actual approval store.
- Add an Agent decision panel showing scene, selected skills, candidate tools, visible tools, RAG/memory hits, approval status, and no-tool/tool-decision reasons.
- Unify version source across `VERSION`, `/api/version`, README, and release notes.

## Acceptance checks

Expected behavior after this branch:

- Simple chat should not expose `host.shell.exec`, `host.powershell.exec`, or `host.python.exec`.
- Knowledge QA should expose read/search tools, not local execution tools.
- Config translation should expose config/workspace tools and should not fall back to local shell.
- Explicit requests such as “执行本机命令 / 查看本机端口 / run PowerShell” may expose local execution tools and still require approval at execution time.
- Complex/parallel/delegated tasks may expose sub-agent coordination tools.
- Same-session concurrent turns should serialize instead of interleaving session history and tool results.
- HTTP SSE responses should identify themselves as `event_replay`.
- WebSocket responses should identify themselves as `live` when live events are emitted, or `event_replay_fallback` otherwise.

## Recommended local validation

```bash
python -m pytest harness/test_agent_hardening_stages.py -q
python -m pytest harness -q
```
