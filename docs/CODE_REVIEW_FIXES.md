# Code Review Findings — 2026-06-09

Baseline commit: `5a56b1f`. Review scope: full codebase including agent graph, nodes, llm, backend API, frontend, modules, runtime, tests, docs.

**Status: ALL HIGH + ALL MEDIUM + key LOW issues RESOLVED.** Architecture refactored with Codex-inspired Context Fragment + Task/Turn models.

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| HIGH | 3 | Needs fix |
| MEDIUM | 12 | Needs fix |
| LOW | 18 | Consider cleanup |
| INFO | 8 | FYI |

---

## HIGH Severity

### 1. `rate_limit.py` — X-Forwarded-For IP spoofing
- **File**: `backend/core/rate_limit.py:104-108`
- **Issue**: Unconditionally trusts `X-Forwarded-For` header. In non-proxy environments, attackers can spoof IPs to bypass rate limits or frame other users.
- **Fix**: Trust only when running behind a verified reverse proxy. Default to `request.remote_addr`.

### 2. Dead code: `agent/{router,planner,executor,verifier,composer}.py`
- **Files**: 5 files in `agent/`, collectively ~200 lines
- **Issue**: These are old LangGraph node implementations superseded by `agent/nodes/`. They reference non-existent `state.done` attribute and are never imported by `agent/graph.py`. If accidentally imported, they'll crash.
- **Fix**: Delete all 5 files.

### 3. `graph.py` — Duplicate `wrap_trace_node` definition
- **File**: `agent/graph.py:50-77`
- **Issue**: First (broken) definition of `wrap_trace_node` that returns None. Only the second definition (lines 117-195) works. Dead code causing confusion.
- **Fix**: Delete lines 50-77.

---

## MEDIUM Severity

### 4. `agent.py` — No message size limit
- **File**: `backend/api/agent.py:37`
- **Issue**: `message` field has no length check. 100MB payload can cause OOM.
- **Fix**: Add `if len(message) > 1_000_000: return 413`.

### 5. `modules_translate.py` — Exception leak to client
- **File**: `backend/api/modules_translate.py:38`
- **Issue**: Raw exception `f"translate_config failed: {exc}"` exposed to client. May leak file paths and config data.
- **Fix**: Log the exception server-side, return a generic error message.

### 6. Composer — LLM config boilerplate repeated 4×
- **File**: `agent/nodes/composer.py:46-61, 112-127, 262-274, 632-643`
- **Issue**: Identical `resolve_provider_config()` + `llm.update()` pattern duplicated 4 times.
- **Fix**: Extract to `_resolve_and_update_llm_context(state, task)` helper.

### 7. `context_loader.py` — Silent exception swallowing
- **File**: `agent/nodes/context_loader.py:38-93`
- **Issue**: 5 `try/except: pass` blocks with zero logging. Debugging impossible in production.
- **Fix**: Add `logger.debug()` or `logger.warning()` in each except block.

### 8. `policy.py` — Secret detection is effectively no-op
- **File**: `agent/llm/policy.py:66-72`
- **Issue**: API key secret detection loop always passes/branches to "too aggressive". No actual secret leaks are caught.
- **Fix**: Implement proper secret pattern matching or remove dead branch.

### 9. `policy.py` — Fragile private import
- **File**: `agent/llm/policy.py:62`
- **Issue**: `from prompts.policy import _is_negation_context` — imports a private function. If `prompts/policy.py` is refactored, policy silently breaks.
- **Fix**: Make `_is_negation_context` a public function or inline the check.

### 10. `rule_translator.py` — Typed IR failure silently falls back
- **File**: `modules/config_translation/core/rule_translator.py:329`
- **Issue**: Typed IR pipeline exceptions are silently caught and fall back to line-by-line factory. No indication in bundle metadata that fallback was used.
- **Fix**: Add `typed_ir_fallback: true` to bundle metadata.

### 11. `tool_planner.py` — Orphan code with duplicated logic
- **File**: `agent/nodes/tool_planner.py`
- **Issue**: `maybe_execute_tool()` never called from any active node. Logic duplicated in `llm_orchestrator.py::_handle_llm_disabled()`.
- **Fix**: Mark as deprecated or delete.

### 12. `llm_orchestrator.py` — Uses private `_executor` attribute
- **File**: `agent/nodes/llm_orchestrator.py:172`
- **Issue**: `client._executor.execute(invocation)` — depends on internal attribute. Breaks if executor is renamed.
- **Fix**: Add a public `execute()` method on the client.

### 13. `_clean_response` duplication
- **Files**: `agent/nodes/llm_orchestrator.py:193-208` and `agent/llm/runtime.py:216-224`
- **Issue**: Identical response cleaning logic in two places.
- **Fix**: Merge into a single shared utility.

### 14. `composer.py` — `state=None` default causes AttributeError
- **Files**: `agent/nodes/composer.py:451, 500`
- **Issue**: `_model_response(state=None)` and `_memory_response(state=None)` — calling `state.warnings.append()` when state is None crashes.
- **Fix**: Make `state` a required parameter, or add None guard.

### 15. `workspace_routes.py` — Sensitive field filter is blacklist
- **File**: `backend/api/workspace_routes.py:86`
- **Issue**: Filters sensitive fields by blacklist (`k not in ("source_config", ...)`). New sensitive fields will silently leak.
- **Fix**: Use whitelist of allowed fields.

---

## LOW Severity

### 16. `graph.py` — `_CANONICAL_NODES` missing orchestrator
- **File**: `agent/graph.py:20-27`
- **Issue**: Only lists 7 nodes but node map supports 8.

### 17. `state.py` — Dataclass not TypedDict
- **File**: `agent/state.py:10`
- **Issue**: Uses `@dataclass` instead of LangGraph `TypedDict`. Depends on `__dataclass_fields__` internals.

### 18. Inconsistent `SECRET_PATTERNS`
- **Files**: `agent/llm/policy.py:9` vs `agent/llm/context_builder.py:7`
- **Issue**: Two different lists of secret keywords defined in the same codebase.

### 19. `planner.py` — Redundant no-op node
- **File**: `agent/nodes/planner.py:9-11`
- **Issue**: `plan()` only checks if `state.plan` is empty — but intent_router already sets it.

### 20. `memory_writer.py` — Unused imports
- **File**: `agent/nodes/memory_writer.py:3,6`
- **Issue**: `json`, `time` imported but never used. `ROOT` computed but never used.

### 21. `provider.py` — `/models` endpoint assumption
- **File**: `agent/llm/provider.py:48`
- **Issue**: Health check uses `/models` endpoint. Not all LLM providers support this.

### 22. `client.py` — Config captured at __init__ time
- **File**: `agent/llm/client.py:11`
- **Issue**: `resolve_provider_config()` called at init, config frozen for client lifetime.

### 23. `settings.py` — Git dependency at import time
- **File**: `backend/core/settings.py:14-25`
- **Issue**: `BUILD_COMMIT` resolved via `git rev-parse` at module import. Fails if deployed without git.

### 24. Frontend `safeSetHTML` — Misleading name
- **File**: `frontend/index.html:1033-1037`
- **Issue**: Function named `safeSetHTML` does zero sanitization. Could cause XSS if developer assumes it's safe.

### 25-33. Minor: unused variables, dead module-level code, etc. (see full review)

---

## Architecture Refactoring (2026-06-09)

After studying OpenAI Codex's agent architecture, two key patterns were adopted:

### 1. Context Fragment System (`context/fragments/`)
- Replaces 5 ad-hoc try/except blocks in `context_loader.py`
- 5 standard fragments: WorkspaceState, MemoryHits, ModuleRegistry, SkillRegistry, ContextBundle
- Each fragment: independent build(), token budget cap, priority ordering, error isolation
- Extensibility: new fragments can be registered without touching loader code
- Inspired by Codex's `ContextualUserFragment` trait + `FragmentRegistration` pattern

### 2. Task/Turn Model (`agent/task.py`, `agent/turn.py`)
- Task: state machine (CREATED → RUNNING → COMPLETED | FAILED | CANCELLED)
- Turn: per-LLM-cycle tracking (tool calls, model response, elapsed, status)
- Integrated into `llm_orchestrator.py` for agentic loop observability
- Inspired by Codex's Session → Task → Turn model

## INFO / Cleanup

### A. `backend/agent/` — Placeholder files
- `backend/agent/graph.py`, `router.py`, `state.py` contain only `pass` stubs. These are future development placeholders causing confusion with the real `agent/` package.

### B. Outdated docstrings
- `agent/llm/__init__.py:3`: "No real models connected yet — skeleton only"
- Multiple docs still reference old commits and test counts (fixed in this batch)

### C. `SSE` exposes pipeline nodes
- `backend/api/sse.py:94-96`: Node names exposed as metadata in SSE events. Not a security issue, but exposes internal architecture.

---

## Architecture Recommendations

1. **Delete dead code**: Remove `agent/{router,planner,executor,verifier,composer}.py` and `agent/graph.py:50-77`.
2. **Promote orchestrator to proper node**: Move `orchestrate()` call out of skill_executor and make it a proper graph node with conditional routing for chat/knowledge intents.
3. **Extract LLM config helper**: Consolidate 4× repeated config resolution in composer.
4. **Unify secret detection**: Single `SECRET_PATTERNS` constant shared across policy and context builder.
5. **Add logging**: Replace all `except: pass` blocks with proper debug-level logging.
6. **Whitelist approach for data filtering**: Replace blacklist-based sensitive field filtering with explicit whitelists.
