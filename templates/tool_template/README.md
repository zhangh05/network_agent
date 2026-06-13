# Tool Template

## Registration: `tool_runtime/general_tools.py`

```python
_reg("category.name", "Display Name", "category", "low",
     "Description", handler_function)
```

## Schema: `GENERAL_TOOL_INPUT_SCHEMAS`

```python
"category.name": _schema({
    "param": {"type": "string", "description": "Description of param"},
    "count": {"type": "integer", "description": "Number of items", "default": 10},
})
```

## Handler

```python
from tool_runtime.schemas import ToolInvocation

def handle_my_tool(inv: ToolInvocation) -> dict:
    args = inv.arguments
    param_val = args.get("param", "")

    try:
        # ... business logic ...
        result = do_something(param_val)
        return _ok({
            "data": result,
            "summary": "Successfully processed",
            "count": len(result),
        })
    except Exception as e:
        return _error(str(e)[:200])
```

## Standardized Return Format

```python
# Success
_ok({"data": result, "summary": "Done"})
# → {"ok": True, "data": result, "summary": "Done"}

# Error
_error("Something went wrong")
# → {"ok": False, "error": "Something went wrong"}
```

## Risk Level Guidelines

| Risk | When to Use | requires_approval |
|------|-------------|-------------------|
| `low` | Read-only, local, no side effects | `False` |
| `medium` | Write ops, network calls, state changes | `False` |
| `high` | Arbitrary execution, system commands | **`True`** |
| `forbidden` | Retired or blocked | `False` (but `callable_by_llm=False`) |

## Test Requirements

- Unit test: per handler function
- Contract test: verify schema, risk, approval
- E2E test: full invocation chain
