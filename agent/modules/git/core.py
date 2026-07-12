# agent/modules/git/core.py
"""Git operations core — wraps git CLI for safe, idempotent operations."""

from __future__ import annotations

import subprocess
import os
from pathlib import Path
from typing import Optional


def _run_git(args: list[str], cwd: str = ".", timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git command timed out"
    except Exception as e:
        return 1, "", str(e)


def _require_repo(path: str) -> Path:
    p = Path(path).resolve()
    if not (p / ".git").exists():
        raise ValueError(f"Not a git repository: {path}")
    return p


def git_clone(url: str, target_dir: str, branch: str = "") -> dict:
    args = ["clone"]
    if branch:
        args += ["-b", branch]
    args += [url, target_dir]
    code, out, err = _run_git(args, cwd=os.getcwd(), timeout=120)
    if code != 0:
        return {"ok": False, "error": err or f"exit {code}"}
    return {"ok": True, "cloned_to": str(Path(target_dir).resolve()), "output": out}


def git_status(repo_path: str) -> dict:
    _require_repo(repo_path)
    code, out, _ = _run_git(["status", "--short", "-b"], cwd=repo_path)
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "repo": str(Path(repo_path).resolve()), "status": out}


def git_log(repo_path: str, n: int = 10, file_path: str = "") -> dict:
    _require_repo(repo_path)
    args = ["log", f"-{n}", "--oneline", "--decorate"]
    if file_path:
        args += ["--", file_path]
    code, out, _ = _run_git(args, cwd=repo_path)
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "log": out}


def git_diff(repo_path: str, staged: bool = False, file_path: str = "") -> dict:
    _require_repo(repo_path)
    args = ["diff"]
    if staged:
        args.append("--staged")
    if file_path:
        args += ["--", file_path]
    code, out, _ = _run_git(args, cwd=repo_path)
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "diff": out[:50000]}


def git_commit(repo_path: str, message: str, files: list[str] | None = None) -> dict:
    _require_repo(repo_path)
    # Stage
    if files:
        code, _, err = _run_git(["add"] + files, cwd=repo_path)
        if code != 0:
            return {"ok": False, "error": f"git add failed: {err}"}
    else:
        return {"ok": False, "error": "files are required; refusing implicit git add -A"}
    # Commit
    code, out, err = _run_git(["commit", "-m", message], cwd=repo_path)
    if code != 0:
        return {"ok": False, "error": err or out}
    return {"ok": True, "message": out}


def git_push(repo_path: str, remote: str = "origin", branch: str = "") -> dict:
    _require_repo(repo_path)
    args = ["push", remote]
    if branch:
        args.append(branch)
    code, out, err = _run_git(args, cwd=repo_path, timeout=60)
    if code != 0:
        return {"ok": False, "error": err or out}
    return {"ok": True, "output": out}


def git_pull(repo_path: str, remote: str = "origin", branch: str = "") -> dict:
    _require_repo(repo_path)
    args = ["pull", remote]
    if branch:
        args.append(branch)
    code, out, err = _run_git(args, cwd=repo_path, timeout=60)
    if code != 0:
        return {"ok": False, "error": err or out}
    return {"ok": True, "output": out}


def git_branch(repo_path: str, action: str = "list", name: str = "") -> dict:
    _require_repo(repo_path)
    if action == "list":
        code, out, _ = _run_git(["branch", "-a"], cwd=repo_path)
        return {"ok": True, "branches": out} if code == 0 else {"ok": False, "error": out}
    elif action == "create":
        code, out, err = _run_git(["checkout", "-b", name], cwd=repo_path)
        return {"ok": code == 0, "output": out or err}
    elif action == "switch":
        code, out, err = _run_git(["checkout", name], cwd=repo_path)
        return {"ok": code == 0, "output": out or err}
    return {"ok": False, "error": f"unknown action: {action}"}
