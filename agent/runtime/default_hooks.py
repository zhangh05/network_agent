"""v3.0.0: Default security hooks — automatically registered at startup.

These hooks provide baseline security without user configuration:
  - PreToolUse: scan tool arguments for injection patterns; block high-risk calls
  - PostToolUse: scan tool results for leaked secrets; inject warnings
  - UserPromptSubmit: sanitize user input for key patterns
  - PostToolCleanup: clean up orphaned sub-sessions and temp files (v3.1.1)
  - Stop: allow normal completion (default pass-through)

All hooks are lightweight (< 5ms per call) and fire on every compatible event.
"""

import logging
import re
import os
import time
from pathlib import Path
from agent.hooks import (
    HookEvent, HookDecision, HookResult, HookDefinition,
)
from agent.hooks_integration import register_hook

_log = logging.getLogger("default_hooks")

# ── Injection patterns (subset of rag_injection_scan HIGH_RISK_PATTERNS) ──

_ARGUMENT_SCAN_PATTERNS = [
    # High-risk command patterns
    (re.compile(r'(rm\s+-rf|sudo\s+rm|format\s+[A-Z]:|del\s+/[FSQ])', re.I),
     "dangerous_command"),
    (re.compile(r'(curl|wget).*(\.env|/etc/passwd|/etc/shadow)', re.I),
     "credential_exfiltration"),
    (re.compile(r'(eval|exec|system|subprocess|__import__)\s*\(', re.I),
     "code_execution"),
    (re.compile(r'(token|api_key|password|secret|credential)\s*[=:]\s*[\'"][^\'"]+[\'"]', re.I),
     "credential_in_argument"),
]

_RESULT_SCAN_PATTERNS = [
    (re.compile(r'(api[_-]?key|token|password|secret|credential)\s*[=:]\s*[\'"][^\'"]{8,}[\'"]', re.I),
     "exposed_credential"),
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})', re.I),
     "openai_key_exposed"),
]

_USER_INPUT_PATTERNS = [
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})', re.I),
     "api_key_in_input"),
    (re.compile(r'(password|passwd|pwd)\s*[=:]\s*\S+', re.I),
     "password_in_input"),
]


def _safe_reason(pattern_name: str, match_text: str) -> str:
    """Redact the matched text to avoid logging sensitive data."""
    return f"blocked:{pattern_name}"


# ═══════════════════════════════════════════════════════════════════
# Hook 1: PreToolUse — scan arguments before tool execution
# ═══════════════════════════════════════════════════════════════════

def _pre_tool_use_handler(state: dict, payload: dict) -> HookResult:
    """Scan tool arguments for injection patterns. Block high-risk calls."""
    arguments = payload.get("arguments", {})
    if not arguments:
        return HookResult()

    arg_text = ""
    try:
        import json
        arg_text = json.dumps(arguments, ensure_ascii=False)
    except Exception:
        arg_text = str(arguments)

    for pattern, name in _ARGUMENT_SCAN_PATTERNS:
        m = pattern.search(arg_text)
        if m:
            _log.warning("PreToolUse blocked: %s tool=%s", name, payload.get("tool_id", "?"))
            return HookResult(
                decision=HookDecision.DENY,
                reason=_safe_reason(name, m.group(0)),
            )

    return HookResult()


# ═══════════════════════════════════════════════════════════════════
# Hook 2: PostToolUse — scan results for leaked secrets
# ═══════════════════════════════════════════════════════════════════

def _post_tool_use_handler(state: dict, payload: dict) -> HookResult:
    """Scan tool results for accidentally leaked credentials."""
    result = payload.get("result", {})
    if not result:
        return HookResult()

    result_text = ""
    try:
        import json
        result_text = json.dumps(result, ensure_ascii=False)
    except Exception:
        result_text = str(result)

    for pattern, name in _RESULT_SCAN_PATTERNS:
        m = pattern.search(result_text)
        if m:
            _log.warning("PostToolUse: exposed credential detected tool=%s", payload.get("tool_id", "?"))
            return HookResult(
                feedback=f"[security] Possible {name} in tool output. Output blocked.",
                metadata={"security_flag": name},
                decision=HookDecision.DENY,
            )

    return HookResult()


# ═══════════════════════════════════════════════════════════════════
# Hook 3: UserPromptSubmit — sanitize user input
# ═══════════════════════════════════════════════════════════════════

def _user_prompt_submit_handler(state: dict, payload: dict) -> HookResult:
    """Scan user input for accidentally pasted credentials or keys."""
    prompt = payload.get("prompt", "") or payload.get("user_input", "")
    if not prompt:
        return HookResult()

    for pattern, name in _USER_INPUT_PATTERNS:
        m = pattern.search(prompt)
        if m:
            _log.warning("UserPromptSubmit: %s detected", name)
            return HookResult(
                decision=HookDecision.DENY,
                reason=f"Input contains possible {name}. Remove credentials and retry.",
                metadata={"security_flag": name},
            )

    return HookResult()


# ═══════════════════════════════════════════════════════════════════
# Hook 4: PostToolCleanup — lightweight resource cleanup (v3.1.1)
# ═══════════════════════════════════════════════════════════════════

# Rate-limit cleanup to once every 300 seconds (5 min)
_LAST_CLEANUP_TS = 0
_CLEANUP_INTERVAL = 300
_CLEANUP_MAX_AGE_SECONDS = 3600  # 1 hour for temp files


def _post_tool_cleanup_handler(state: dict, payload: dict) -> HookResult:
    """Periodic cleanup: orphaned sub-sessions, stale temp dirs, expired caches."""
    global _LAST_CLEANUP_TS
    now = time.time()
    if now - _LAST_CLEANUP_TS < _CLEANUP_INTERVAL:
        return HookResult()
    _LAST_CLEANUP_TS = now

    workspace_id = (state or {}).get("workspace_id") or payload.get("workspace_id", "")
    cleaned = 0

    try:
        # ── Clean up orphaned sub-agent session directories ──
        from workspace.manager import WS_ROOT
        sessions_dir = WS_ROOT / workspace_id / "sessions"
        if sessions_dir.is_dir():
            for item in sessions_dir.iterdir():
                # Sub-agent sessions are named sub_<run_id>
                if not item.name.startswith("sub_"):
                    continue
                # Check if the session JSON exists and has no runs
                json_path = sessions_dir / f"{item.name}.json"
                if json_path.exists():
                    try:
                        import json
                        data = json.loads(json_path.read_text())
                        # Soft-delete sub-agent sessions with no runs after 10 minutes
                        if not data.get("run_ids") and data.get("status") == "active":
                            age = now - json_path.stat().st_mtime
                            if age > 600:  # 10 minutes
                                from workspace.session_store import soft_delete_session
                                soft_delete_session(item.name, workspace_id)
                                cleaned += 1
                    except Exception:
                        pass
                elif item.is_dir():
                    # Orphaned directory (no .json) — check if it's old
                    age = now - item.stat().st_mtime
                    if age > _CLEANUP_MAX_AGE_SECONDS:
                        import shutil
                        shutil.rmtree(str(item), ignore_errors=True)
                        cleaned += 1

        # ── Clean up stale python_exec temp dirs ──
        temp_dir = WS_ROOT / workspace_id / "sys" / "tmp" / "python_exec"
        if temp_dir.is_dir():
            for item in temp_dir.iterdir():
                if item.is_dir():
                    age = now - item.stat().st_mtime
                    if age > _CLEANUP_MAX_AGE_SECONDS:
                        import shutil
                        shutil.rmtree(str(item), ignore_errors=True)
                        cleaned += 1
    except Exception:
        pass  # Cleanup is best-effort

    if cleaned > 0:
        _log.debug("PostToolCleanup: cleaned %d items in workspace %s", cleaned, workspace_id)

    return HookResult()


# ═══════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_HOOKS = [
    HookDefinition(
        event=HookEvent.PRE_TOOL_USE,
        handler=_pre_tool_use_handler,
        priority=0,
        matcher=r".*",  # match all tools
        hook_id="arg_security_scan",
    ),
    HookDefinition(
        event=HookEvent.POST_TOOL_USE,
        handler=_post_tool_use_handler,
        priority=0,
        matcher=r".*",
        hook_id="result_security_scan",
    ),
    HookDefinition(
        event=HookEvent.USER_PROMPT_SUBMIT,
        handler=_user_prompt_submit_handler,
        priority=0,
        matcher=r".*",
        hook_id="input_credential_scan",
    ),
    HookDefinition(
        event=HookEvent.POST_TOOL_USE,
        handler=_post_tool_cleanup_handler,
        priority=100,  # Run after result_security_scan (priority=0)
        matcher=r".*",
        hook_id="post_tool_cleanup",
    ),
]


def register_default_hooks():
    """Register all default security hooks. Idempotent — safe to call multiple times."""
    for hook in _DEFAULT_HOOKS:
        try:
            register_hook(hook)
        except Exception as e:
            _log.debug("Failed to register hook %s: %s", hook.hook_id, e)

    _log.info("Default security hooks registered: %d hooks", len(_DEFAULT_HOOKS))
