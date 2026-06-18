# tool_runtime/builtins.py
"""v0.1 built-in low-risk tools.

Four baseline tools are provided:
  1. workspace.artifact.list       — list artifact summaries (no full content)
  2. network.config.parse          — shallow safe parsing of config text
  3. network.interface.extract     — extract interface names (no full blocks)
  4. network.route.extract         — extract route-like line summaries

All tools are risk_level=low and dry_run_supported=True.
None execute real device commands, shells, or arbitrary file access.
"""

from tool_runtime.schemas import ToolSpec, ToolInvocation
from tool_runtime.registry import ToolRegistry


def _enrich_result(invocation, d):
    out = dict(d)
    if "tool_id" not in out:
        out["tool_id"] = getattr(invocation, "tool_id", "")
    if "status" not in out:
        out["status"] = "ok" if out.get("ok") else "failed"
    if "errors" not in out and not out.get("ok"):
        msg = out.get("error") or out.get("summary") or "failed"
        out["errors"] = [msg]
    if "summary" not in out:
        out["summary"] = "Completed."
    return out

# ═══════════════════════════════════
# Tool Handlers
# ═══════════════════════════════════

def _handler_artifact_list(invocation: ToolInvocation) -> dict:
    """List artifact summaries for a workspace. Returns metadata only."""
    workspace_id = invocation.arguments.get("workspace_id", invocation.workspace_id or "default")
    try:
        from workspace.manager import get_workspace_state
        state = get_workspace_state(workspace_id)
        items = []
        # Artifacts are tracked in workspace state with refs
        art_refs = state.get("artifact_refs", []) if isinstance(state, dict) else []
        return {
            "ok": True,
            "tool_id": "workspace.artifact.list",
            "status": "ok",
            "summary": f"Listed {len(art_refs)} artifact references",
            "artifacts": art_refs[:50],  # limit to 50 entries
            "workspace_id": workspace_id,
            "warnings": ["Artifact list is metadata-only; no full content returned"] if art_refs else [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "tool_id": "workspace.artifact.list",
            "status": "failed",
            "summary": f"Failed to list artifacts: {str(exc)[:100]}",
            "artifacts": [],
            "warnings": [f"workspace.artifact.list failed: {str(exc)[:100]}"],
        }


def _handler_parser_parse_config_text(invocation: ToolInvocation) -> dict:
    """Shallow safe parse of config text. Returns statistics only."""
    text = invocation.arguments.get("config_text", "")
    if not text:
        return _enrich_result(invocation, {"ok": False, "summary": "No config_text provided", "warnings": ["config_text required"]})

    lines = text.split("\n")
    non_empty = [l for l in lines if l.strip() and not l.strip().startswith("!")]
    line_count = len(lines)
    non_empty_count = len(non_empty)

    # Heuristic vendor detection
    vendor_hint = "unknown"
    text_lower = text.lower()
    if "huawei" in text_lower or "vlanif" in text_lower or "sysname" in text_lower:
        vendor_hint = "huawei"
    elif "h3c" in text_lower or "comware" in text_lower:
        vendor_hint = "h3c"
    elif "cisco" in text_lower or "ios" in text_lower or "enable" in text_lower:
        vendor_hint = "cisco"
    elif "ruijie" in text_lower:
        vendor_hint = "ruijie"

    # Block detection
    has_interface = "interface " in text_lower or "interface\n" in text_lower
    has_acl = "access-list" in text_lower or "acl" in text_lower
    has_route = "ip route" in text_lower or "route " in text_lower

    warnings = []
    if line_count > 10000:
        warnings.append("Large config detected, consider splitting")

    return _enrich_result(invocation, {
        "ok": True,
        "summary": f"Parsed {line_count} lines ({non_empty_count} non-empty), vendor={vendor_hint}",
        "line_count": line_count,
        "non_empty_line_count": non_empty_count,
        "vendor_hint": vendor_hint,
        "has_interface_blocks": has_interface,
        "has_acl_like_lines": has_acl,
        "has_route_like_lines": has_route,
        "warnings": warnings,
    })


def _handler_parser_extract_interfaces(invocation: ToolInvocation) -> dict:
    """Extract interface names from config text. No full interface blocks returned."""
    text = invocation.arguments.get("config_text", "")
    if not text:
        return _enrich_result(invocation, {"ok": False, "summary": "No config_text provided", "warnings": ["config_text required"]})

    import re
    # Match interface definitions: "interface GigabitEthernet0/0/1" etc
    pattern = re.compile(r'^\s*(?:interface|int)\s+(\S+)', re.IGNORECASE | re.MULTILINE)
    matches = pattern.findall(text)

    interface_names = list(dict.fromkeys(matches))  # dedup, preserve order
    total = len(interface_names)
    limited = interface_names[:100]

    warnings = []
    if total > 100:
        warnings.append(f"Truncated from {total} to 100 interfaces")

    return _enrich_result(invocation, {
        "ok": True,
        "summary": f"Found {total} unique interface names",
        "interface_count": total,
        "interface_names": limited,
        "truncated": total > 100,
        "warnings": warnings,
    })


def _handler_parser_extract_routes(invocation: ToolInvocation) -> dict:
    """Extract route-like line summaries. No full config blocks."""
    text = invocation.arguments.get("config_text", "")
    if not text:
        return _enrich_result(invocation, {"ok": False, "summary": "No config_text provided", "warnings": ["config_text required"]})

    import re
    # Match static route patterns
    route_pattern = re.compile(
        r'^\s*(?:ip\s+)?route(?:-static)?\s+(.+)$', re.IGNORECASE | re.MULTILINE
    )
    matches = route_pattern.findall(text)

    # Sanitize: strip sensitive-looking content
    sanitized = []
    for m in matches:
        clean = m.strip()[:120]
        # Mask potential IPs with partial redaction (keep structure)
        clean = re.sub(r'(\d{1,3}\.\d{1,3})\.\d{1,3}\.\d{1,3}', r'\1.x.x', clean)
        sanitized.append(clean)

    total = len(sanitized)
    limited = sanitized[:100]
    warnings = []
    if total > 100:
        warnings.append(f"Truncated from {total} to 100 route lines")

    return _enrich_result(invocation, {
        "ok": True,
        "summary": f"Found {total} route-like lines",
        "route_count": total,
        "route_summaries": limited,
        "truncated": total > 100,
        "warnings": warnings,
    })


# ═══════════════════════════════════
# ToolSpec Definitions
# ═══════════════════════════════════

BUILTIN_TOOLS = [
    (
        ToolSpec(
            tool_id="workspace.artifact.list",
            name="List Artifacts",
            description="List artifact metadata summaries for a workspace. Use when: user wants to browse available artifacts before reading one. Read-only. No full content returned — use workspace.artifact.read_content_safe for previews. Returns artifact_id, title, type for each entry.",
            category="artifact",
            risk_level="low",
            reads_artifact=True,
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                },
            },
        ),
        _handler_artifact_list,
    ),
    (
        ToolSpec(
            tool_id="network.config.parse",
            name="Parse Config Text",
            description="Shallow safe parse of network device configuration text. Use when: user provides config text and you need vendor detection, block analysis, and structure hints. Returns vendor_hint, line counts, and block type detection (interfaces/ACL/routes). Read-only. Safe — no device access. Use BEFORE network.interface.extract or network.route.extract for context.",
            category="network",
            risk_level="low",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["config_text"],
                "properties": {
                    "config_text": {"type": "string", "description": "Network device configuration text to parse (offline — no device access needed)."},
                },
            },
        ),
        _handler_parser_parse_config_text,
    ),
    (
        ToolSpec(
            tool_id="network.interface.extract",
            name="Extract Interfaces",
            description="Extract interface names from network device configuration text. Use when: user provides config and asks about interfaces, port mapping, or topology. No full interface blocks returned — only names. Read-only. Use workspace.artifact.save to preserve results. For full interface config blocks, use workspace.file.read on the uploaded config.",
            category="network",
            risk_level="low",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["config_text"],
                "properties": {
                    "config_text": {"type": "string", "description": "Network device configuration text to parse (offline — no device access needed)."},
                },
            },
        ),
        _handler_parser_extract_interfaces,
    ),
    (
        ToolSpec(
            tool_id="network.route.extract",
            name="Extract Routes",
            description="Extract route-like line summaries from network device configuration text. Use when: user provides config and asks about routing table, static routes, or path analysis. IPs are partially masked for safety. Read-only. Returns sanitized route summaries. Use with text.redact for additional safety before sharing.",
            category="network",
            risk_level="low",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["config_text"],
                "properties": {
                    "config_text": {"type": "string", "description": "Network device configuration text to parse (offline — no device access needed)."},
                },
            },
        ),
        _handler_parser_extract_routes,
    ),
]


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register all v0.1 built-in tools into the given registry.

    Returns the same registry for chaining.
    """
    for spec, handler in BUILTIN_TOOLS:
        registry.register_tool(spec, handler)
    return registry


def create_registry_with_builtins() -> ToolRegistry:
    """Create a ToolRegistry and register all built-in tools.

    Convenience factory for tests and runtime initialization.
    """
    return register_builtin_tools(ToolRegistry())
