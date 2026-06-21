"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_command_approved_exec(inv: ToolInvocation) -> dict:
    """Shell command execution on Linux/macOS.

    Accepts a shell command string, executes via /bin/bash -c.
    Safety limits: 30s timeout, 10000 chars output, workspace-root cwd.
    Requires approval_id (high risk). Policy blocks destructive patterns.
    """
    import platform
    if platform.system() == "Windows":
        return _unavailable(inv, "Shell execution only available on Linux/macOS. Use host.powershell.exec on Windows.")
    # Only accept `command`; alternate identifiers are never executed as shell.
    command = (inv.arguments.get("command") or "").strip()
    if not command:
        return _unavailable(inv, "command is required")
    result = _run_shell(command)
    return _result(inv, result.pop("ok", False), result)

def handle_powershell_approved_script(inv: ToolInvocation) -> dict:
    """PowerShell script execution on Windows.

    Accepts a PowerShell command string, executes via powershell -Command.
    Safety limits: 15s timeout, 10000 chars output.
    Requires approval_id (high risk). Policy blocks destructive patterns.
    """
    import platform
    if platform.system() != "Windows":
        return _unavailable(inv, "PowerShell execution only available on Windows. Use host.shell.exec on Linux/macOS.")
    command = (inv.arguments.get("command") or "").strip()
    if not command:
        return _unavailable(inv, "command is required")
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=15,
        )
        stdout = (result.stdout or "")[:_SHELL_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_SHELL_MAX_OUTPUT]
        return _ok(inv, f"PowerShell command finished (exit={result.returncode}).", {
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        })
    except subprocess.TimeoutExpired:
        return _error_inv(inv, "command timed out after 15s")
    except FileNotFoundError:
        return _error_inv(inv, "powershell not found")
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_slash_run(inv: ToolInvocation) -> dict:
    """Execute a slash command via the command system."""
    args = inv.arguments
    command = str(args.get("command", "")).strip()
    cmd_args = str(args.get("args", "")).strip()

    if not command:
        return _error_inv(inv, "command is required")

    try:
        from agent.runtime.command_system import execute_command
        result = execute_command(command, cmd_args, getattr(inv, 'session_id', None), getattr(inv, 'workspace_id', None))
        return _ok(inv, f"Slash command '{command}' executed.", {"command": command, "result": result})
    except ImportError:
        return _error_inv(inv, "command system not available")
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_python_exec(inv: ToolInvocation) -> dict:
    """Execute Python code in an AST-checked sandbox.

    High risk tool. Code is parsed with AST to reject forbidden imports,
    builtins, and dunder access before execution. Runs in a subprocess with
    timeout. Requires explicit user approval.
    """
    workspace_id = inv.arguments.get("workspace_id", "default")
    run_id = inv.arguments.get("run_id", "")
    code = str(inv.arguments.get("code", "")).strip()
    timeout = min(int(inv.arguments.get("timeout", 10) or 10), 10)

    if not code:
        return _error_inv(inv, "code is required")

    try:
        validate_workspace_id(workspace_id)
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code(
            code=code,
            workspace_id=workspace_id,
            run_id=run_id,
            timeout=timeout,
        )
        return _result(inv, result.pop("ok", False), result)
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_command_approved_exec', 'handle_powershell_approved_script', 'handle_slash_run', 'handle_python_exec']
