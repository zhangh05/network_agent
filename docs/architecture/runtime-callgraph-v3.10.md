# Runtime Call Graph — v3.10 Architecture Baseline

> Phase 1 deliverable. Documents the **single current call chain**.
> No legacy fallbacks, no dual-store, no bypass paths.
> Generated: 2026-06-26

## Entry Points

| Entry | Transport | Path | Handler |
|-------|----------|------|---------|
| WebSocket | WS | `/ws/agent` | `backend/ws/agent_ws.py` |
| HTTP (async) | HTTP POST | `/api/agent/message` | `backend/api/agent_routes.py` |
| SSE (observe) | HTTP SSE | `/api/agent/sse/stream/<id>` | `backend/api/runtime_routes.py` |
| Job Runner | API/Scheduler | `/api/jobs/<id>/run` | `jobs/runner.py` |

## Unified Entry: AgentApp

All four entry points converge on:

```
AgentApp.submit_user_message(user_input, session_id, workspace_id, metadata)
  → session_manager.get_or_create(session_id, workspace_id)
  → AgentThread(session).submit(op)
  → AgentSession.submit(op)
  → run_turn(session, turn, services)
```

## Runtime Engine: TurnRunner

```
run_turn()                          # loop.py:96
  → TurnRunner.run()                # runner.py:61
    → TurnRuntimeState()            # Construct runtime state
    → RuntimeEventBus(state)        # Event bus
    → ContextStage.run(state)       # Build context
    → MessageStage.run(state)       # Build messages
    → while step < max_steps:       # Agentic loop
      → ModelStage.run(state, events)
      → if tool_calls:
        → ToolExecutionPipeline.run(state, resp, events)
          → for each tool_call:
            → tool_router.build_tool_call()
            → _execute_single_with_retry()
              → _execute_single()
                → ActionPlanner.plan()
                → ActionExecutor.execute()
                  → RiskPolicy.evaluate()
                  → ApprovalGate.decide()
                  → ToolDispatcher.dispatch()
                    → ToolRuntimeClient.invoke()
                      → ToolExecutor.execute()
                        → handler(invocation)
                  → ResultNormalizer.normalize()
                  → ResultScanner.scan()
                  → AuditTrail.record()
                → push_tool_done()        # SSE real-time
            → push_turn_done()            # SSE real-time
      → else:
        → events.turn_completed()
        → build_success_result()
    → persist_run_record()          # turn_persistence.py
    → Job lifecycle update          # jobs/manager
```

## Approval Path

```
ActionExecutor.execute()
  → RiskPolicy.evaluate(plan)
    → _check_dangerous_commands()  # rm -rf, curl|sh, chmod 777, etc.
    → _is_execute_tool()           # shell/powershell/python exec
    → action_class routing: read→low, write→medium, mutate→medium-high
  → ApprovalGate.decide(plan, risk)
    → blocked → rejected
    → high/critical/medium-high → pending → ApprovalStore.create()
    → low/medium → not_required
  → if pending: _wait_for_approval() blocks, frontend ApprovalBubble polls
  → resolve → allow/deny → continue/abort
```

## Event Path

```
Three-layer event system:

1. StreamEmitter (query_engine.py)
   → Thread-local realtime_callback → WebSocket push
   → Accumulated events → result.events

2. RuntimeEventBus (runtime_events.py)
   → Wraps StreamEmitter + Audit

3. SessionEvents (session_events.py)
   → Per-session queue.Queue → SSE Endpoint → frontend EventSource
   → Pushed from ToolExecutionPipeline (_execute_single)
```

## Persistence Path

```
persist_run_record(session, turn, result, context)  # turn_persistence.py
  → run_store.write_run_record()    → workspace/<ws>/runs/<id>.json
  → message_store.write_message()   → workspace/<ws>/messages/<sid>/
  → trace persistence               → workspace/<ws>/runs/<id>.trace.json

ApprovalStore                       # agent/approval.py
  → data/tool_approvals.jsonl       # Append-only, 90-day retention

JobStore                            # jobs/store.py
  → workspace/<ws>/jobs/<id>.json
```

## Legacy Search Results

| Pattern | Found? | Notes |
|---------|--------|-------|
| `legacy` as runtime mode | **No** | Only internal variable names, test data strings |
| `_tool_approvals` | **No** | Removed in v3.9, using unified ApprovalStore |
| `canonical_registry.dispatch()` | **No** | All dispatch through ToolRuntimeClient |
| direct handler invoke | **No** | All handlers go through ActionExecutor pipeline |
| `"default"` workspace fallback | **No** | facade.py default is type-level; routes validate ws_id |
| `AgentInspector` | **No** | Removed in v3.9 Phase 6 |
| `AGENT SYSTEM` | **No** | Only in regex injection scan patterns |
| dual approval store | **No** | Single ApprovalStore in agent/approval.py |

## Remaining v3.8 Version Comments

These are in active files marking features introduced in v3.8.
They do not indicate dual paths or legacy code. Bumped to v3.10 in cleanup.

## Module Index

| Module | Role | Level |
|--------|------|-------|
| `backend/ws/agent_ws.py` | WebSocket handler | Entry |
| `backend/api/agent_routes.py` | HTTP handler | Entry |
| `backend/api/runtime_routes.py` | SSE + runtime API | Entry |
| `agent/app/facade.py` | AgentApp entry | Facade |
| `agent/app/session_manager.py` | Session lifecycle | Facade |
| `agent/core/session.py` | AgentSession | Core |
| `agent/runtime/loop.py` | run_turn() | Core |
| `agent/runtime/runner.py` | TurnRunner | Core |
| `agent/runtime/tool_execution/pipeline.py` | ToolExecutionPipeline | Execution |
| `agent/runtime/actions/executor.py` | ActionExecutor | Execution |
| `agent/runtime/actions/risk.py` | RiskPolicy | Execution |
| `agent/runtime/actions/approval.py` | ApprovalGate | Execution |
| `agent/runtime/actions/dispatcher.py` | ToolDispatcher | Execution |
| `tool_runtime/client.py` | ToolRuntimeClient | Runtime |
| `tool_runtime/executor.py` | ToolExecutor | Runtime |
| `tool_runtime/integration.py` | Client factory | Runtime |
| `tool_runtime/canonical_registry.py` | Tool registry | Runtime |
| `agent/approval.py` | ApprovalStore | System |
| `agent/runtime/session_events.py` | SSE event bus | System |
| `agent/runtime/turn_persistence.py` | Persistence | System |
| `agent/runtime/runtime_events.py` | RuntimeEventBus | System |
| `workspace/run_store.py` | Run storage | System |
| `workspace/message_store.py` | Message storage | System |
| `jobs/runner.py` | Job executor | System |
| `jobs/manager.py` | Job state | System |
| `frontend/src/pages/AgentWorkbench/AgentWorkbench.tsx` | Workbench | Frontend |
| `frontend/src/api/index.ts` | API layer | Frontend |
| `frontend/src/stores/workbench.ts` | State store | Frontend |
| `frontend/src/components/RuntimeEventTimeline.tsx` | Timeline | Frontend |

## Verification Commands

```bash
# Verify no legacy bypass
git grep -n "_tool_approvals" backend/api/runtime_routes.py          # Should be empty
git grep -n "canonical_registry\.dispatch" agent/ runtime_routes.py  # Should be empty
git grep -n -i "legacy" agent/runtime/loop.py                        # Should be empty

# Verify single approval store
git grep -n "_tool_approvals\|_APPROVALS_FILE" agent/ backend/      # Should be empty

# Verify no AgentInspector
git grep -rn "AgentInspector" frontend/src/                          # Should be empty

# Verify workspace validation
git grep -n "default.*workspace_id\|workspace_id.*default" backend/api/*routes.py | grep -v "#"
```
