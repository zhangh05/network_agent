# Module Template

v3.9.4 uses one business capability catalog and 21 canonical tools. A module
does not register tools directly. New module work follows this order:

1. Add or update a business capability entry in `agent/capabilities/catalog.py`.
2. Reference only canonical tool ids from `tool_runtime/tool_namespace.py`.
3. Put deterministic domain logic in `agent/modules/<name>/service.py`.
4. If a canonical tool needs to call the module, wire it through
   `tool_runtime/canonical_registry.py`.
5. Validate with `python3 -m pytest harness/test_business_capability_catalog.py harness/test_v394_no_legacy_tool_ids.py -q`.

## Structure

```text
agent/modules/<name>/
  service.py       # deterministic business logic
  tools.py         # optional internal adapters called by a canonical tool
  __init__.py
```

## Catalog Entry

```python
{
    "capability_id": "my_feature",
    "display_name": "My Feature",
    "description": "Describe the business outcome.",
    "module_ids": ("my_feature",),
    "recommended_tool_ids": ("workspace.file", "text.analyze"),
    "prompt_hints": ("Read workspace inputs before analysis.",),
    "safety_notes": ("Do not access live devices.",),
    "status": "planned",
}
```

`recommended_tool_ids` must be canonical ids. Do not add legacy pre-merge tool
names such as `device.list`, `web.search`, or `pcap.analysis.run`.
