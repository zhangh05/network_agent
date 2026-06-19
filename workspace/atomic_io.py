"""Atomic filesystem IO helpers — shared by workspace, session, and runtime code.

These helpers make state on disk resilient to process crashes: a failed
write never corrupts the existing file. Patterns use POSIX tmp + os.replace
which is atomic on the same filesystem.

Public API:
- atomic_write_text(path, text)  — write a UTF-8 text file atomically
- atomic_write_json(path, obj)   — dump obj as JSON and write atomically
- safe_read_text(path, default)  — read a file, returning default on any error
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional


# P1 fix (round 7): per-call tmp filename with pid+uuid to prevent
# concurrent writers from clobbering each other's tmp file. With a
# single shared `.tmp` suffix, two processes/threads writing to the
# same target would race in the open() call (O_TRUNC after the loser
# already wrote data) and the resulting os.replace could install a
# half-written file. The `pid.uuid` suffix keeps tmp paths unique
# across processes and threads (uuid4 makes intra-process collisions
# impossible too).
def _unique_tmp(path: Path) -> Path:
    suffix = f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    return path.with_name(path.name + suffix)


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp + os.replace).

    On any failure the original file at ``path`` is left untouched.
    On POSIX systems, os.replace is atomic on the same filesystem so
    concurrent readers never observe a half-written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp(path)
    # O_EXCL prevents two writers from racing into the same tmp path
    # even on unusual filesystems where the pid+uuid suffix could
    # still collide (e.g. tmpfs shared between containers).
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync may fail on some filesystems / OSes; the data is
                # already written, just not durable across power loss.
                pass
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any, *, indent: Optional[int] = 2) -> None:
    """Serialize ``obj`` as JSON and write atomically."""
    text = json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
    atomic_write_text(Path(path), text)


def safe_read_text(path: Path, default: str = "") -> str:
    """Read a file's contents; return default on any failure.

    Useful for state files that may be missing or temporarily empty
    during a concurrent write.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return default
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return default


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON from path; return default on any error (missing, malformed, IO)."""
    try:
        p = Path(path)
        if not p.is_file():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default
