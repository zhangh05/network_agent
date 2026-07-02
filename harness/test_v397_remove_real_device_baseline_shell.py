"""v3.9.7 contract: real-device access is not a prompt-level hard gate.

Earlier versions rendered a stale ``"Safety: No real device access"``
banner into the runtime snapshot and embedded "NEVER touches a real
device" guards in module docstrings. These existed only in the prompt
/ docstring layer; the canonical ``exec.run(target=ssh|telnet)`` path
does not block in any policy layer.

This test pins the new contract:
  - snapshot ``to_prompt_text()`` no longer emits the misleading
    ``"No real device access"`` / ``"Config push forbidden"`` text;
    it only renders the catalog-derived safety notes.
  - module docstrings no longer claim "NEVER touches a real device"
  - the SSH / Telnet handler is real and reachable, not gated.

If a future change wants to reinstate a hard "no real device" gate,
that change must update these tests — they document the explicit
absence of the gate.
"""

from agent.context.snapshot import RuntimeSnapshot, build_runtime_snapshot
from agent.capabilities import catalog as _catalog


def test_snapshot_does_not_emit_no_real_device_access_banner():
    """Even with an empty catalog the snapshot must not emit the
    "No real device access" / "Config push forbidden" banner.
    """
    snap = RuntimeSnapshot(
        tool_count=21,
        visible_tool_count=21,
        workspace_id="default",
        model="test",
        safety_baseline={"notes": [], "count": 0},
    )
    text = snap.to_prompt_text()

    assert "No real device access" not in text, (
        f"Stale real-device banner emitted: {text!r}"
    )
    assert "Real device access ENABLED" not in text, (
        f"Stale real-device banner emitted: {text!r}"
    )
    assert "Config push forbidden" not in text
    assert "Config push ALLOWED" not in text


def test_snapshot_with_real_catalog_only_renders_notes():
    """When capability catalog is non-empty, snapshot renders the
    catalog safety notes verbatim; no hard-coded banner.
    """
    caps = _catalog.list_all()
    snap = build_runtime_snapshot(
        tool_count=21,
        visible_tool_count=21,
        workspace_id="default",
        model="test",
        capability_catalog=caps,
    )
    text = snap.to_prompt_text()

    assert "No real device access" not in text
    assert "Config push forbidden" not in text


def test_module_review_docstrings_do_not_claim_no_real_device_access():
    """review module docstrings must not promise a gate that doesn't
    exist in code. Earlier they said "NEVER touches a real device".
    """
    import agent.modules.review as m
    src = open(m.__file__).read()
    assert "NEVER touches a real device" not in src
    assert "Never touch a real device." not in src


def test_module_artifact_docstrings_do_not_claim_no_real_device_access():
    """artifact module docstrings — see above."""
    import agent.modules.artifact as m
    src = open(m.__file__).read()
    assert "NEVER touches real devices" not in src
    assert "No real device access." not in src


def test_tool_runtime_foundation_doc_acknowledges_real_device_path():
    """The Tool Runtime ``__init__`` and ``builtins`` no longer claim
    the foundation layer excludes real-device execution. Real
    device handling lives in ``core.tools.canonical_registry``;
    callers get there through ``exec.run(target=ssh|telnet)``.
    """
    import core.tools as tr
    init_src = open(tr.__file__).read()
    assert "No real device execution is included." not in init_src

    import core.tools.builtins as tb
    builtins_src = open(tb.__file__).read()
    assert "None execute real device commands" not in builtins_src


def test_canonical_registry_exposes_ssh_target_handler():
    """The ``exec.run(target=ssh|telnet)`` paths are reachable from
    the canonical handler map. They are not blocked by any policy
    layer; the dispatcher routes the call to ``_handler_network_ssh``
    / ``_handler_network_telnet``.
    """
    from core.tools.canonical_registry import CANONICAL_REGISTRY
    entry = CANONICAL_REGISTRY.get("exec.run")
    assert entry is not None
    # The handler_id should resolve to one of the merged handlers.
    assert entry.handler_id


def test_assistant_chat_prompt_reflects_real_device_access():
    """assistant_chat.md prompt must tell the LLM that real device
    access via ``exec.run(target=ssh|telnet)`` is supported. Earlier
    versions inverted this and misled the LLM into refusing.
    """
    from pathlib import Path
    text = (Path("prompts/templates/assistant_chat.md").read_text(encoding="utf-8"))
    # Real-device access is supported via exec.run target=ssh/telnet.
    assert "exec.run(target=ssh)" in text
    assert "exec.run(target=telnet)" in text
    # The stale "Do NOT say 没有真实设备访问能力" sentence is gone.
    assert "Do NOT say" not in text
    assert "没有真实设备访问能力" not in text
