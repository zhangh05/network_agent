# Business Capability Template

Business capabilities are catalog entries, not runtime registrations. The LLM
can only call canonical tools exposed by the runtime. Capabilities guide tool
choice and UI display.

## Registration

1. Edit `agent/capabilities/catalog.py`.
2. Use canonical ids from the 21-tool namespace only.
3. Keep `status="planned"` until the underlying canonical tool path works.
4. Run:

```bash
python3 -m pytest harness/test_business_capability_catalog.py harness/test_v394_no_legacy_tool_ids.py -q
```

## Template

```python
{
    "capability_id": "my_feature",
    "display_name": "My Feature",
    "description": "One sentence describing the outcome.",
    "module_ids": ("my_feature",),
    "recommended_tool_ids": ("workspace.file", "text.analyze"),
    "prompt_hints": ("Use workspace.file before parsing user files.",),
    "safety_notes": ("Never claim unverified output is deployable.",),
    "status": "planned",
}
```
