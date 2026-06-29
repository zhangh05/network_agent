# Business Capability Template

Business capabilities describe user-facing outcomes. They are not tool registrations and do not dispatch handlers.

## Add Or Update A Capability

1. Edit `agent/capabilities/catalog.py`.
2. Reference only canonical tool IDs from `tool_runtime/tool_namespace.py`.
3. Keep `status="planned"` until the runtime path and tests exist.
4. Run:

```bash
python3 -m pytest harness/test_business_capability_catalog.py harness/test_v394_no_legacy_tool_ids.py -q
```

## Entry Shape

```python
{
    "capability_id": "my_feature",
    "display_name": "My Feature",
    "description": "One sentence describing the user outcome.",
    "module_ids": ("my_feature",),
    "recommended_tool_ids": ("workspace.file", "text.analyze"),
    "prompt_hints": ("Read source files before producing analysis.",),
    "safety_notes": ("Do not claim unverified output is deployable.",),
    "status": "planned",
}
```

Do not add tool aliases or separate capability registries.
