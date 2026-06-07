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
| Greeting | `assistant_chat` | Deterministic greeting + capability hints |
| Identity Q | `assistant_chat` | "I'm Network Agent..." |
| Capability Q | `assistant_chat` | Lists enabled + planned + safety notes |
| Help / Thanks | `assistant_chat` | Guidance + farewell |
| Explain last | `context_qa` | Summarizes last run, manual_review, quality |
| Config translate | `translate_config` | Executes config_translation skill |
| Topology/Inspection/etc | `topology_draw` etc | Returns coming_soon |
| Unknown | `unknown` | Friendly suggestion with available capabilities |

## Execution Model for assistant_chat

```
router → intent=assistant_chat
  → planner → no-op plan
  → executor → no-op (returns early)
  → composer → _assistant_response(state)
  → memory_writer → writes summary only
```

- No skill loaded, no module called, no tool invoked
- No deployable_config generated
- No job/artifact/report created

## Safety Red Lines

1. assistant_chat NEVER enters business module
2. assistant_chat NEVER calls Tool Runtime
3. assistant_chat NEVER generates deployable_config
4. LLM (if enabled) goes through Prompt Runtime policy
5. deterministic fallback always available
6. Manual review not hidden
7. High risk not downgraded
8. No "可直接下发" claims
