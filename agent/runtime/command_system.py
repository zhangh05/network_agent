# agent/runtime/command_system.py
"""Slash-command registry and executor.

Provides a pluggable command system similar to Codex slash commands.
Commands are registered with a name and handler, and can be invoked
via the /slash.run tool or directly through the runtime.
"""

from typing import Any, Callable, Optional

# dict of command_name -> handler
# Handler signature: handler(args: str, session_id: str | None, context: dict | None) -> str
SLASH_COMMANDS: dict[str, Callable[[str, Optional[str], Optional[dict]], str]] = {}

# Command metadata: command_name -> {"description": str, "category": str}
_COMMAND_META: dict[str, dict] = {}


def register_command(name: str, handler, description: str = "", category: str = "general") -> None:
    """Register a slash command.

    Args:
        name: Command name (without leading /). E.g. 'help', 'tools'.
        handler: Callable(args: str, session_id: str|None, context: dict|None) -> str
        description: Human-readable description shown in /help.
        category: Grouping category for listing.
    """
    clean_name = name.lstrip("/")
    SLASH_COMMANDS[clean_name] = handler
    _COMMAND_META[clean_name] = {"description": description, "category": category}


def get_command(name: str):
    """Get a command handler by name. Returns None if not found."""
    clean_name = name.lstrip("/")
    return SLASH_COMMANDS.get(clean_name)


def list_commands(category: str = "") -> list[dict]:
    """List all registered commands with metadata.

    Args:
        category: Optional filter by category. If empty, returns all.

    Returns:
        List of dicts with name, description, category.
    """
    results = []
    for name, meta in sorted(_COMMAND_META.items()):
        if category and meta.get("category") != category:
            continue
        results.append({
            "name": f"/{name}",
            "description": meta.get("description", ""),
            "category": meta.get("category", "general"),
        })
    return results


def execute_command(name: str, args: str = "", session_id: Optional[str] = None,
                    workspace_id: Optional[str] = None) -> str:
    """Execute a slash command.

    Args:
        name: Command name (with or without leading /).
        args: Optional arguments string.
        session_id: Current session id.
        workspace_id: Current workspace id.

    Returns:
        Formatted result string.
    """
    clean_name = name.lstrip("/")
    handler = SLASH_COMMANDS.get(clean_name)

    if not handler:
        available = ", ".join(f"/{n}" for n in sorted(SLASH_COMMANDS.keys()))
        return f"Unknown command: /{clean_name}\nAvailable commands: {available}"

    context = {}
    if workspace_id:
        context["workspace_id"] = workspace_id

    try:
        return handler(args, session_id, context)
    except Exception as e:
        return f"Command /{clean_name} failed: {str(e)[:200]}"


# ═══════════════════════════
# Built-in command handlers
# ═══════════════════════════

def _cmd_help(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """List all available slash commands."""
    lines = ["# Available Slash Commands\n"]
    by_category: dict[str, list[str]] = {}
    for cmd_name, meta in sorted(_COMMAND_META.items()):
        cat = meta.get("category", "general")
        by_category.setdefault(cat, []).append(cmd_name)

    for cat in sorted(by_category):
        lines.append(f"## {cat}")
        for cmd_name in by_category[cat]:
            meta = _COMMAND_META[cmd_name]
            lines.append(f"  /{cmd_name} — {meta.get('description', '')}")
        lines.append("")

    if not args:
        return "\n".join(lines)

    # Show help for specific command
    target = args.strip().lstrip("/")
    meta = _COMMAND_META.get(target)
    if meta:
        return f"/{target} — {meta.get('description', '')}\nCategory: {meta.get('category', 'general')}"
    return f"No help available for: /{target}"


def _cmd_tools(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """List model-visible tools (filtered, not all)."""
    try:
        from agent.runtime.services import default_runtime_services
        services = default_runtime_services()
        tools = services.tool_service.registry.list_model_visible()
    except Exception:
        return _format_command_result({
            "ok": False, "status": "error", "command": "tools",
            "result": "", "errors": ["Tool registry not available."],
            "warnings": [], "metadata": {},
        })

    if args.strip():
        keyword = args.strip().lower()
        tools = [t for t in tools if keyword in t.tool_id.lower() or keyword in (t.description or "").lower()]

    lines = ["# Model-Visible Tools\n"]
    for t in tools[:50]:
        risk = getattr(t, 'risk_level', '?')
        lines.append(f"  {t.tool_id} [{risk}] — {getattr(t, 'description', '')[:100]}")
    lines.append(f"\nTotal: {len(tools)} model-visible tools.")

    return _format_command_result({
        "ok": True, "status": "ok", "command": "tools",
        "result": "\n".join(lines),
        "errors": [], "warnings": [],
        "metadata": {"tool_count": len(tools), "filtered": bool(args.strip())},
    })


def _cmd_skills(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """List skills."""
    try:
        from pathlib import Path
        skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
        if not skills_dir.is_dir():
            return "No skills directory found."
        results = []
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            yaml_path = item / "skill.yaml"
            desc = ""
            status = "unknown"
            if yaml_path.is_file():
                try:
                    import yaml
                    with open(yaml_path, encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    desc = str(data.get("description", ""))[:80]
                    status = str(data.get("status", "unknown"))
                except Exception:
                    pass
            results.append(f"  {item.name} [{status}] — {desc}")
        return "# Skills\n" + "\n".join(results) if results else "No skills installed."
    except Exception as e:
        return f"Failed to list skills: {e}"


def _cmd_memory(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """List memories."""
    ws_id = (context or {}).get("workspace_id", "default")
    try:
        from workspace.memory_store import list_memories
        memories = list_memories(ws_id, limit=20)
    except Exception:
        return "Memory store not available."

    lines = ["# Memories\n"]
    for m in memories:
        title = m.get("title", "?")[:60]
        scope = m.get("scope", "?")
        status = m.get("status", "?")
        lines.append(f"  [{scope}/{status}] {title}")
    lines.append(f"\nTotal: {len(memories)} memories.")
    return "\n".join(lines)


def _cmd_context(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Show context stats."""
    lines = ["# Context Stats\n"]

    # Session info
    if session_id:
        lines.append(f"Session: {session_id}")
    if context:
        ws_id = context.get("workspace_id", "")
        if ws_id:
            lines.append(f"Workspace: {ws_id}")

    # Try to get token usage
    try:
        from agent.runtime.token_tracker import estimate_messages
        # This is a rough estimate — actual tracking depends on session state
        lines.append("Token tracking: available via /usage")
    except Exception:
        pass

    # Try history length
    try:
        from agent.core.session import AgentSession
        if session_id:
            lines.append("History: check /sessions for details")
    except Exception:
        pass

    return "\n".join(lines)


def _cmd_sessions(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """List sessions."""
    ws_id = (context or {}).get("workspace_id", "default")
    try:
        from workspace.session_store import list_sessions
        sessions = list_sessions(ws_id)
    except Exception:
        return "Session store not available."

    lines = ["# Sessions\n"]
    for s in sessions[:20]:
        sid = s.get("session_id", "?")[:16]
        title = s.get("title", "?")[:60]
        status = s.get("status", "?")
        lines.append(f"  {sid} [{status}] — {title}")
    lines.append(f"\nTotal: {len(sessions)} sessions.")
    return "\n".join(lines)


def _cmd_compact(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Trigger manual context compaction."""
    try:
        from agent.runtime.context_compactor import compact_messages
        # Build a minimal messages list from session history for compaction
        messages = []
        if session_id:
            try:
                from workspace.message_store import SessionMessageStore
                ws_id = (context or {}).get("workspace_id", "default")
                store = SessionMessageStore(session_id=session_id, ws_id=ws_id)
                if store.exists():
                    window = store.get_history_window(k=16)
                    for m in window:
                        if m.get("role") == "user":
                            messages.append({"role": "user", "content": m.get("content", "")})
                        elif m.get("role") == "assistant":
                            messages.append({"role": "assistant", "content": m.get("content", "")})
            except Exception:
                pass
        if not messages:
            return _format_command_result({
                "ok": True, "status": "ok", "command": "compact",
                "result": "No messages to compact.",
                "errors": [], "warnings": ["no_messages"],
                "metadata": {},
            })
        compacted, meta = compact_messages(messages, keep_recent=6)
        result_text = (
            f"Compacted {meta.get('compacted_message_count', 0)} messages. "
            f"Tokens: {meta.get('original_estimated_tokens', '?')} → {meta.get('compacted_estimated_tokens', '?')}."
        )
        return _format_command_result({
            "ok": True, "status": "ok", "command": "compact",
            "result": result_text,
            "errors": [], "warnings": [],
            "metadata": {
                "compacted": meta.get("compacted", False),
                "compacted_message_count": meta.get("compacted_message_count", 0),
                "original_estimated_tokens": meta.get("original_estimated_tokens", 0),
                "compacted_estimated_tokens": meta.get("compacted_estimated_tokens", 0),
            },
        })
    except Exception as e:
        return _format_command_result({
            "ok": False, "status": "error", "command": "compact",
            "result": "", "errors": [str(e)[:200]],
            "warnings": [], "metadata": {},
        })


def _cmd_usage(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Show token usage stats."""
    try:
        from agent.runtime.token_tracker import estimate_messages
        ws_id = (context or {}).get("workspace_id", "default")
        # Try to get real usage from token tracker
        usage_stats = {}
        try:
            from agent.runtime.token_tracker import get_usage
            usage_stats = get_usage(ws_id) or {}
        except Exception:
            pass

        if usage_stats:
            result_lines = [
                f"Workspace: {ws_id}",
                f"Total calls: {usage_stats.get('total_calls', 'N/A')}",
                f"Total input tokens: {usage_stats.get('total_input_tokens', 'N/A')}",
                f"Total output tokens: {usage_stats.get('total_output_tokens', 'N/A')}",
                f"Max context: {usage_stats.get('max_context_tokens', 128000)}",
            ]
            result_text = "Token Usage:\n" + "\n".join(result_lines)
        else:
            result_text = (
                "Token usage is tracked per-turn during execution.\n"
                "Default limits: 128K input, 16K output.\n"
                "Compaction triggers automatically at 70% context utilization."
            )

        return _format_command_result({
            "ok": True, "status": "ok", "command": "usage",
            "result": result_text,
            "errors": [], "warnings": [],
            "metadata": usage_stats or {"note": "no usage stats available"},
        })
    except Exception as e:
        return _format_command_result({
            "ok": False, "status": "error", "command": "usage",
            "result": "", "errors": [str(e)[:200]],
            "warnings": [], "metadata": {},
        })


def _cmd_agent(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Show agent info."""
    lines = [
        "# Agent Info",
        "Network Agent Node v1.0",
        "Runtime: Codex-style agentic loop",
        "Tools: General + Agent + Skill + Runtime",
        "Commands: Use /help for available slash commands.",
    ]
    try:
        from agent.runtime.services import default_runtime_services
        services = default_runtime_services()
        tool_count = len(services.tool_service.registry.list_all())
        lines.append(f"Loaded tools: {tool_count}")
    except Exception:
        pass
    return "\n".join(lines)


def _cmd_reset(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Reset conversation (archive current session, clear history)."""
    ws_id = (context or {}).get("workspace_id", "default")
    if not session_id:
        return _format_command_result({
            "ok": False, "status": "error", "command": "reset",
            "result": "", "errors": ["No session to reset. session_id is required."],
            "warnings": [], "metadata": {},
        })
    try:
        from workspace.message_store import SessionMessageStore
        store = SessionMessageStore(session_id=session_id, ws_id=ws_id)
        # Mark existing messages as archived (don't delete)
        if store.exists():
            archived_count = store.archive_all() or len(store.get_history_window(k=200))
        else:
            archived_count = 0
        # Also update session store to mark as archived
        try:
            from workspace.session_store import archive_session
            archive_session(ws_id, session_id)
        except Exception:
            pass

        return _format_command_result({
            "ok": True, "status": "ok", "command": "reset",
            "result": f"Session {session_id} reset. {archived_count} messages archived.",
            "errors": [], "warnings": [],
            "metadata": {"archived_count": archived_count, "session_id": session_id},
        })
    except Exception as e:
        return _format_command_result({
            "ok": False, "status": "error", "command": "reset",
            "result": "", "errors": [str(e)[:200]],
            "warnings": [], "metadata": {},
        })


def _cmd_export(args: str, session_id: Optional[str], context: Optional[dict]) -> str:
    """Export session to JSON."""
    ws_id = (context or {}).get("workspace_id", "default")
    if not session_id:
        return _format_command_result({
            "ok": False, "status": "error", "command": "export",
            "result": "", "errors": ["No session to export. session_id is required."],
            "warnings": [], "metadata": {},
        })
    try:
        from workspace.session_store import get_session
        session = get_session(session_id, ws_id)
        if not session:
            return _format_command_result({
                "ok": False, "status": "error", "command": "export",
                "result": "", "errors": [f"Session {session_id} not found."],
                "warnings": [], "metadata": {},
            })
        messages = session.get("messages", [])
        export_data = {
            "session_id": session_id,
            "workspace_id": ws_id,
            "title": session.get("title", ""),
            "status": session.get("status", "active"),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "message_count": len(messages),
            "messages": [
                {"role": m.get("role", ""), "content": str(m.get("content", ""))[:1000]}
                for m in messages[:50]
            ],
        }
        import json
        formatted = json.dumps(export_data, ensure_ascii=False, indent=2)
        return _format_command_result({
            "ok": True, "status": "ok", "command": "export",
            "result": formatted,
            "errors": [], "warnings": [],
            "metadata": {"message_count": len(messages), "truncated": len(messages) > 50},
        })
    except Exception as e:
        return _format_command_result({
            "ok": False, "status": "error", "command": "export",
            "result": "", "errors": [str(e)[:200]],
            "warnings": [], "metadata": {},
        })


def _format_command_result(structured: dict) -> str:
    """Format a structured command result into a readable string.

    Args:
        structured: Dict with ok, status, command, result, errors, warnings, metadata.

    Returns:
        Formatted markdown string suitable for display.
    """
    lines = [f"# /{structured.get('command', 'unknown')}\n"]
    lines.append(f"Status: {structured.get('status', 'unknown')}")
    lines.append(f"OK: {structured.get('ok', False)}")

    if structured.get("errors"):
        lines.append(f"\nErrors: {', '.join(structured['errors'])}")
    if structured.get("warnings"):
        lines.append(f"\nWarnings: {', '.join(structured['warnings'])}")

    result = structured.get("result", "")
    if result:
        lines.append(f"\n{result}")

    meta = structured.get("metadata", {})
    if meta:
        meta_lines = [f"  {k}: {v}" for k, v in meta.items()]
        lines.append(f"\nMetadata:\n" + "\n".join(meta_lines))

    return "\n".join(lines)


# ═══════════════════════════
# Register built-in commands
# ═══════════════════════════

def register_default_commands() -> None:
    """Register all built-in slash commands."""
    register_command("help", _cmd_help, "List all available slash commands", "system")
    register_command("tools", _cmd_tools, "List visible tools", "system")
    register_command("skills", _cmd_skills, "List installed skills", "agent")
    register_command("memory", _cmd_memory, "List memories in current workspace", "agent")
    register_command("context", _cmd_context, "Show context stats", "session")
    register_command("sessions", _cmd_sessions, "List sessions in current workspace", "session")
    register_command("compact", _cmd_compact, "Trigger manual context compaction", "session")
    register_command("usage", _cmd_usage, "Show token usage information", "system")
    register_command("agent", _cmd_agent, "Show agent runtime info", "system")
    register_command("reset", _cmd_reset, "Reset conversation (clear history)", "session")
    register_command("export", _cmd_export, "Export current session", "session")


# Auto-register on module load
register_default_commands()
