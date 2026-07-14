from __future__ import annotations

from pathlib import Path
import os
from types import SimpleNamespace

from core.tools.general_tools import command_tools
from core.tools.general_tools.shared import _run_shell, _shell_argv
from core.tools.schemas import ToolInvocation


ROOT = Path(__file__).resolve().parents[1]


def _inv(tool_id: str, **arguments) -> ToolInvocation:
    return ToolInvocation(
        tool_id=tool_id,
        arguments=arguments,
        workspace_id="default",
        requested_by="turn_runner",
    )


def test_native_windows_shell_uses_cmd_exe(monkeypatch):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    assert _shell_argv("echo hello", os_name="nt") == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
        "echo hello",
    ]


def test_exec_run_propagates_native_shell_failure(monkeypatch):
    monkeypatch.setattr(
        command_tools,
        "_run_shell",
        lambda *args, **kwargs: {
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "command failed",
            "error": "command failed",
        },
    )
    result = command_tools.handle_command_approved_exec(
        _inv("exec.run", command="where missing-command")
    )
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["error"] == "command failed"


def test_native_shell_nonzero_exit_is_failed():
    command = "exit /b 7" if os.name == "nt" else "exit 7"
    result = _run_shell(command)
    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert result["error"] == "Command exited with code 7"


def test_powershell_respects_cwd_timeout_env_and_exit_code(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(returncode=7, stdout="", stderr="bad command")

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("shutil.which", lambda name: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    monkeypatch.setattr("subprocess.run", fake_run)
    result = command_tools.handle_powershell_approved_script(
        _inv(
            "exec.run",
            command="Get-Item missing",
            working_dir=str(tmp_path),
            timeout=45,
            env_vars={"NETWORK_AGENT_TEST": "ok", "OPENAI_API_KEY": "blocked"},
        )
    )

    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert result["error"] == "bad command"
    assert captured["cwd"] == str(tmp_path)
    assert captured["timeout"] == 45
    assert captured["env"]["NETWORK_AGENT_TEST"] == "ok"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["argv"][-2:] == ["-Command", "Get-Item missing"]


def test_windows_launchers_delegate_to_single_powershell_implementation():
    start_bat = (ROOT / "start.bat").read_text(encoding="utf-8")
    stop_bat = (ROOT / "stop.bat").read_text(encoding="utf-8")
    start_ps1 = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert "start.ps1" in start_bat
    assert "stop.ps1" in stop_bat
    assert "-ExecutionPolicy Bypass" in start_bat
    assert "startup-error.log" in start_bat
    assert "notepad.exe" in start_bat
    assert "VITE_DEV_API_TARGET" in start_ps1
    assert '"preview"' in start_ps1
    assert "quotedViteScript" in start_ps1
    assert "ValidateOnly" in start_ps1
    assert "--without-pip" in start_ps1
    assert "startup-error.log" in start_ps1
    assert "Using bundled Windows dependency cache" in start_ps1
    assert 'foreach ($minor in @("3.12", "3.13"))' in start_ps1
    assert "retrying from the configured Python package index" in start_ps1
    assert "ForEach-Object" in start_ps1


def test_windows_release_verifies_every_supported_python_cache_offline():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.12"' in workflow
    assert 'python-version: "3.13"' in workflow
    assert workflow.count("pip download --only-binary=:all:") == 2
    assert "Verify dependency cache offline" in workflow
    assert "--no-index --find-links wheelhouse -r requirements.txt" in workflow
    assert "import flask, flask_sock, yaml" in workflow
