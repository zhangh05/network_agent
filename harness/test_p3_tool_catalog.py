"""P3 tool-catalog snapshot contracts."""


def test_catalog_snapshot_is_cached_and_has_stable_identity():
    from tool_runtime.catalog_snapshot import (
        build_catalog_snapshot,
        reset_catalog_snapshot_cache,
    )

    reset_catalog_snapshot_cache()
    first = build_catalog_snapshot()
    second = build_catalog_snapshot()

    assert first is second
    assert first["catalog_version"] == "tool_catalog.v2"
    assert first["catalog_fingerprint"]
    assert first["count"] == len(first["tools"])
    assert all(
        item["canonical_tool_id"] == item["tool_id"]
        for item in first["tools"]
    )
    assert all(category["count"] >= 0 for category in first["categories"])
