# Agent Experience Model v0.1

## Design Principle

Network Agent is a **chat-entry-driven Agent platform** — not a traditional form-based tool.

Users interact through natural language. The Agent understands intent, routes to capabilities only when business tasks are explicitly requested, and stays in conversational mode for everything else.

## Intent Routing Model

```
User Input
  → router.infer()
    → assistant_chat: greeting, identity, capability, help, thanks
    → context_qa: explain last result, why failure, what manual_review means
    → translate_config: explicit translation request
    → topology_draw: topology request → planned/coming_soon
    → inspection_analyze: inspection request → planned/coming_soon
    → knowledge_search: knowledge request → planned/coming_soon
    → unknown: everything else → friendly suggestion
```

## Conversation vs Business Task

| Type | Intent | Behavior |
|------|--------|----------|
| Greeting | `assistant_chat` | LLM (MiniMax-M3) with deterministic fallback |
| Identity Q | `assistant_chat` | LLM response with capability hints |
| Capability Q | `assistant_chat` | LLM lists enabled + planned + safety notes |
| Help / Thanks | `assistant_chat` | LLM guidance + farewell |
| Explain last | `context_qa` | Summarizes last run, manual_review, quality |
| Config translate | `translate_config` | Executes config_translation skill |
| Topology/Inspection/etc | `topology_draw` etc | Returns coming_soon |
| Unknown | `unknown` | Friendly suggestion with available capabilities |

## Conversation Persistence (v3.1+)

Agent conversations are now organized into **Sessions**:

- Each `POST /api/agent/run` can include a `session_id`
- Sessions group runs into persistent chat threads
- Page load restores full conversation history from backend session store
- `localStorage` only holds `na_current_session_id` — not message content
- Archive/soft-delete preserve run records for audit; permanent delete only removes session metadata

## Execution Model for assistant_chat

```
router → intent=assistant_chat
  → planner → no-op plan
  → executor → no-op (returns early)
  → composer → _compose_assistant_chat(state)
      → try safe_generate("assistant_chat") → MiniMax-M3
      → fallback: _assistant_response(state) if LLM disabled/blocked
  → memory_writer → writes summary only
```

- LLM path: `safe_generate → get_prompt_by_task → render_prompt → check_prompt_text → check_prompt_input → provider(MiniMax-M3) → check_prompt_output → response`
- Deterministic fallback: always available if LLM fails (provider error, policy block, disabled)
- No skill loaded, no module called, no tool invoked
- No deployable_config generated
- No job/artifact/report created

## Intent Router: Config Text Detection

The router now recognizes raw network configuration text via command keywords:

```
hostname, interface, ip address, no shutdown, router ospf/bgp,
ospf, bgp, isis, vlan, acl, gigabitethernet, network 10./172./192.168.
```

When a user pastes raw config text (without explicit "translate" keywords), it routes to `translate_config` automatically.

## Safety Red Lines

1. assistant_chat NEVER enters business module
2. assistant_chat NEVER calls Tool Runtime
3. assistant_chat NEVER generates deployable_config
4. LLM goes through Prompt Runtime policy with negation context detection
5. deterministic fallback always available
6. Manual review not hidden
7. High risk not downgraded
8. No "可直接下发" claims (LLM disclaimers using negation NOT blocked)
