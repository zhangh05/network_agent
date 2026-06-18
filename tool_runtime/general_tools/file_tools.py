"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_file_list(inv: ToolInvocation) -> dict:
    """List files in workspace subdirectory. Max 50 files."""
    ws = inv.arguments.get("workspace_id", "default")
    subdir = inv.arguments.get("subdir", "")
    try:
        target = _validate_workspace_path(ws, subdir)
        if not target.exists():
            return _ok(inv, "", {"files": [], "count": 0})
        files = []
        for p in sorted(target.iterdir()):
            if len(files) >= 50:
                break
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "suffix": p.suffix})
            elif p.is_dir():
                files.append({"name": p.name, "type": "directory"})
        return _ok(inv, "", {"files": files, "count": len(files)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_file_exists(inv: ToolInvocation) -> dict:
    """Check whether a workspace file exists and return metadata."""
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        exists = target.exists()
        result = {
            "exists": exists,
            "is_file": target.is_file() if exists else False,
            "is_dir": target.is_dir() if exists else False,
        }
        if exists and target.is_file():
            result["size"] = target.stat().st_size
        return _ok(inv, f"Path exists={exists}.", result)
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_file_read(inv: ToolInvocation) -> dict:
    """Read workspace text file up to 50000 chars. Rejects binary files."""
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    limit = min(int(inv.arguments.get("limit", 50000)), 50000)
    try:
        target = _validate_workspace_path(ws, filepath)
        if not target.is_file():
            return _error_inv(inv, "file not found")
        if target.stat().st_size > 1024 * 1024:
            return _error_inv(inv, "file too large (>1MB)")
        # Reject binary files
        with open(target, "rb") as f:
            head = f.read(1024)
        if b"\x00" in head:
            return _result(inv, False, {
                "ok": False,
                "error": "binary file cannot be read as text",
                "file_size": target.stat().st_size,
            })
        content = target.read_text(encoding="utf-8", errors="replace")
        preview = content[:limit]
        return _ok(inv, "", {
            "preview": preview,
            "size": len(content),
            "truncated": len(content) > limit,
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_file_edit(inv: ToolInvocation) -> dict:
    """Edit a workspace file by string replacement. Only writes to workspaces/<ws>/files/."""
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    old_string = inv.arguments.get("old_string", "")
    new_string = inv.arguments.get("new_string", "")
    replace_all = bool(inv.arguments.get("replace_all", False))
    try:
        target = _validate_workspace_path(ws, filepath)
        files_root = (WS_ROOT / ws / "files").resolve()
        in_files = any(
            str(target).startswith(str(files_root / src))
            for src in ("upload", "agent")
        )
        if not in_files:
            return _error_inv(inv, "file.edit only writes to workspaces/<ws>/files/upload/ or files/agent/ directory")
        if not target.is_file():
            return _error_inv(inv, "file not found")
        content = target.read_text(encoding="utf-8")
        if replace_all:
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)
        else:
            if old_string not in content:
                return _error_inv(inv, "old_string not found in file")
            count = 1
            new_content = content.replace(old_string, new_string, 1)
        if new_content == content:
            return _ok(inv, "", {"lines_changed": 0, "note": "no changes made"})
        # Generate preview/diff before writing
        diff_preview = _generate_diff_preview(old_string, new_string)
        target.write_text(new_content, encoding="utf-8")
        lines_changed = abs(new_content.count("\n") - content.count("\n")) or count
        return _ok(inv, "", {
            "lines_changed": lines_changed,
            "replacements": count,
            "preview": diff_preview,
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_file_patch(inv: ToolInvocation) -> dict:
    """Apply a unified diff patch to a workspace file. Writes to temp first, then renames."""
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    patch_text = inv.arguments.get("patch_text", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        if not target.is_file():
            return _error_inv(inv, "file not found")
        original = target.read_text(encoding="utf-8")
        original_lines = original.splitlines(keepends=True)
        # Parse unified diff hunks: @@ -old_start,old_count +new_start,new_count @@ body
        hunks = re.findall(
            r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@\n?(.*?)(?=@@|\Z)",
            patch_text, re.DOTALL,
        )
        if not hunks:
            return _error_inv(inv, "no valid diff hunks found in patch_text")
        lines_added = 0
        lines_removed = 0
        result_lines = list(original_lines)
        # Apply in reverse to preserve line offsets
        for hunk in reversed(hunks):
            old_start = int(hunk[0]) - 1
            old_count = int(hunk[1]) if hunk[1] else 1
            new_start = int(hunk[2]) - 1
            new_count = int(hunk[3]) if hunk[3] else 1
            body = hunk[4]
            new_lines = []
            for line in body.split("\n"):
                if not line:
                    new_lines.append("\n")
                elif line.startswith("+"):
                    new_lines.append(line[1:] + "\n")
                    lines_added += 1
                elif line.startswith("-"):
                    lines_removed += 1
                elif line.startswith(" "):
                    new_lines.append(line[1:] + "\n")
            result_lines[old_start:old_start + old_count] = new_lines
        new_content = "".join(result_lines)
        # Write to temp file first, then atomically rename to avoid half-written state
        temp_path = target.with_suffix(target.suffix + ".patch_tmp")
        temp_path.write_text(new_content, encoding="utf-8")
        temp_path.replace(target)
        return _ok(inv, "", {
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "diff_preview": _generate_diff_preview(original[:500], new_content[:500]),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_ws_list_files(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    subdir = inv.arguments.get("subdir", "")
    try:
        target = _validate_workspace_path(ws, subdir)
        if not target.exists():
            return _ok(inv, "", {"files": [], "count": 0})
        files = []
        for p in target.iterdir():
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "suffix": p.suffix})
            elif p.is_dir():
                files.append({"name": p.name, "type": "directory"})
        return _ok(inv, "", {"files": files[:50], "count": len(files)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_ws_read_text_preview(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        if not target.is_file():
            return _error_inv(inv, "file not found")
        if target.stat().st_size > 1024 * 1024:
            return _error_inv(inv, "file too large (>1MB)")
        content = target.read_text(encoding="utf-8", errors="replace")
        return _ok(inv, "", {"preview": _safe_preview(content, 500), "size": len(content)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_ws_write_artifact_file(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filename = inv.arguments.get("filename", "output.txt")
    content = str(inv.arguments.get("content", ""))
    try:
        validate_workspace_id(ws)
        out_dir = WS_ROOT / ws / "files" / "agent"
        out_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        out_file = out_dir / safe_name
        out_file.write_text(content, encoding="utf-8")
        return _ok(inv, "", {"filepath": str(out_file.relative_to(ROOT)), "size": len(content)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_ws_path_exists(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        return _ok(inv, "", {"exists": target.exists(), "is_file": target.is_file(), "is_dir": target.is_dir()})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_ws_get_metadata(inv: ToolInvocation) -> dict:
    ws = inv.arguments.get("workspace_id", "default")
    try:
        target = _validate_workspace_path(ws)
        return _ok(inv, "", {
            "workspace_id": ws,
            "exists": target.exists(),
            "artifact_count": len(list((target / "files").iterdir())) if (target / "files").exists() else 0,
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_file_read_image(inv: ToolInvocation) -> dict:
    """Read image file metadata and attempt OCR-style description.
    
    Returns image dimensions, format, size, and a placeholder for
    the user to describe what's in the image if vision models aren't available.
    """
    ws = inv.arguments.get("workspace_id", "default")
    filepath = inv.arguments.get("filepath", "")
    try:
        target = _validate_workspace_path(ws, filepath)
        if not target.is_file():
            return _error_inv(inv, f"file not found: {filepath}")
        if target.stat().st_size > 20 * 1024 * 1024:
            return _error_inv(inv, "image too large (>20MB)")
        
        suffix = target.suffix.lower()
        img_exts = {".png",".jpg",".jpeg",".gif",".webp",".bmp",".tiff",".ico",".svg"}
        if suffix not in img_exts:
            return _error_inv(inv, f"not an image file: {suffix}")
        
        # Try to get image dimensions using PIL if available
        dims = ""
        try:
            from PIL import Image
            with Image.open(target) as img:
                dims = f"{img.width}x{img.height}"
        except Exception:
            dims = "unknown"
        
        return _ok(inv, f"Image {target.name} ({dims})", {
            "filename": target.name,
            "size": target.stat().st_size,
            "format": suffix.lstrip("."),
            "dimensions": dims,
            "filepath": filepath,
            "workspace_id": ws,
            "note": "Image file saved. If you need to analyze the content, ask the user to describe what the image shows, or use a vision-capable model.",
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_file_list', 'handle_file_exists', 'handle_file_read', 'handle_file_edit', 'handle_file_patch', 'handle_ws_list_files', 'handle_ws_read_text_preview', 'handle_ws_write_artifact_file', 'handle_ws_path_exists', 'handle_ws_get_metadata']
