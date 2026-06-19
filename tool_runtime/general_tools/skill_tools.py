"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_skill_list(inv: ToolInvocation) -> dict:
    """List skills available in the skills/ directory. Read skill.yaml first, then SKILL.md."""
    try:
        skills_dir = ROOT / "skills"
        if not skills_dir.is_dir():
            return _ok(inv, "", {"results": [], "count": 0})
        results = []
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(".") or item.name in ("__pycache__",):
                continue
            skill_info = {"name": item.name, "path": str(item.relative_to(ROOT)), "description": "", "status": "unknown", "capabilities": []}
            # Read skill.yaml first
            yaml_path = item / "skill.yaml"
            if yaml_path.is_file():
                try:
                    import yaml
                    with open(yaml_path, encoding="utf-8") as fy:
                        data = yaml.safe_load(fy)
                    if isinstance(data, dict):
                        skill_info["description"] = str(data.get("description") or data.get("display_name") or "")
                        skill_info["status"] = str(data.get("status", "unknown"))
                        skill_info["capabilities"] = [c.get("capability_id", "") for c in (data.get("capabilities") or []) if isinstance(c, dict)]
                except Exception:
                    pass
            # Fall back to SKILL.md if no description from yaml
            if not skill_info.get("description"):
                md_path = item / "SKILL.md"
                if md_path.is_file():
                    try:
                        md_text = md_path.read_text(encoding="utf-8")[:500]
                        # Extract first meaningful line after headings
                        for line in md_text.split("\n"):
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#"):
                                skill_info["description"] = stripped[:200]
                                break
                    except Exception:
                        pass
            results.append(skill_info)
        return _ok(inv, "", {"results": results, "count": len(results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_skill_request_load(inv: ToolInvocation) -> dict:
    """Request loading a skill — records the request but does NOT inject system prompt.

    skill.load is the preferred way to activate skills.
    """
    args = inv.arguments
    skill_name = str(args.get("skill_name", "")).strip()
    reason = str(args.get("reason", "")).strip()
    ws = args.get("workspace_id", "default")
    sid = args.get("session_id", "")

    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    # Verify skill exists in skills/ directory or registry
    skills_dir = ROOT / "skills"
    found = False
    if skills_dir.is_dir():
        target = skills_dir / skill_name
        if target.is_dir() and not skill_name.startswith("."):
            found = True

    if not found:
        return _error_inv(inv, f"skill '{skill_name}' not found in skills directory")

    # Record request to workspace (optional, best-effort)
    try:
        import json
        req_path = WS_ROOT / ws / "sys" / "skill_requests.jsonl"
        with open(req_path, "a") as f:
            f.write(json.dumps({
                "skill_name": skill_name, "reason": reason,
                "session_id": sid, "workspace_id": ws,
                "requested_at": __import__('time').strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return _ok(inv, "", {
        "requested": True,
        "skill_name": skill_name,
        "message": "skill.load is the preferred way to activate skills; this request has been recorded",
    })

def handle_skill_load(inv: ToolInvocation) -> dict:
    """Runtime-controlled skill loading. Checks skill exists, records as loaded in
    session metadata, and returns SKILL.md content as skill_prompt field.

    Does NOT directly inject into system prompt — the context builder reads
    loaded skills from session metadata via skill_snapshot.

    Safety gates:
    - Blocks pending_review skills
    - Blocks skills matching high-risk patterns (exec, shell, powershell)
    - Stores loaded_skills in ctx.metadata for session-scoped persistence
    """
    import time as _time
    args = inv.arguments
    skill_name = str(args.get("skill_name", "")).strip()
    ws = args.get("workspace_id", "default")
    sid = args.get("session_id", "")

    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    # Sanitize skill name
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", skill_name)
    if not safe_name:
        return _error_inv(inv, f"invalid skill_name: {skill_name}")

    # ── High-risk pattern check ──
    HIGH_RISK_PATTERNS = {"exec", "shell", "powershell", "command.exec", "command_exec"}
    if safe_name.lower() in HIGH_RISK_PATTERNS or any(p in safe_name.lower() for p in HIGH_RISK_PATTERNS):
        return _error_inv(inv, f"skill '{safe_name}' matches high-risk pattern — loading blocked")

    # Check skill exists in skills/ directory
    skills_dir = ROOT / "skills"
    skill_dir = skills_dir / safe_name
    md_path = skill_dir / "SKILL.md"

    if not skill_dir.is_dir() or safe_name.startswith("."):
        return _error_inv(inv, f"skill '{safe_name}' not found in skills directory")

    # ── Status gate: block pending_review skills ──
    yaml_path = skill_dir / "skill.yaml"
    skill_status = "unknown"
    if yaml_path.is_file():
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as fy:
                yaml_data = yaml.safe_load(fy)
            skill_status = str(yaml_data.get("status", "unknown"))
        except Exception:
            pass
    if skill_status == "pending_review":
        return _error_inv(inv, f"skill '{safe_name}' has status=pending_review — must be reviewed before loading")

    # Read SKILL.md content
    try:
        skill_prompt = md_path.read_text(encoding="utf-8")
    except Exception as e:
        return _error_inv(inv, f"failed to read SKILL.md: {str(e)[:200]}")

    # Record loaded skill in session metadata
    loaded_at = _time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        session_meta_path = WS_ROOT / ws / "sessions" / sid / "meta.json"
        if sid and session_meta_path.parent.exists():
            session_meta_path.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            meta = {}
            if session_meta_path.is_file():
                try:
                    meta = _json.loads(session_meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            loaded_skills = meta.setdefault("loaded_skills", {})
            if not isinstance(loaded_skills, dict):
                loaded_skills = {}
            # Store skill_prompt truncated to 3000 chars
            loaded_skills[safe_name] = {
                "skill_prompt": skill_prompt[:3000],
                "loaded_at": loaded_at,
            }
            meta["loaded_skills"] = loaded_skills
            # P1 fix (round 7): write session meta atomically. Previous
            # write_text would leave the file truncated if the process
            # crashed mid-write, and next load would JSONDecodeError.
            from workspace.atomic_io import atomic_write_json
            atomic_write_json(session_meta_path, meta)
    except Exception:
        pass

    return _ok(inv, "", {
        "skill_name": safe_name,
        "loaded_at": loaded_at,
        "prompt_length": len(skill_prompt),
    })

def handle_skill_find(inv: ToolInvocation) -> dict:
    """Search for skills by keyword in their descriptions."""
    args = inv.arguments
    query = str(args.get("query", "")).strip().lower()
    limit = int(args.get("limit", 10))

    if not query:
        return _error_inv(inv, "query is required")

    try:
        skills_dir = ROOT / "skills"
        if not skills_dir.is_dir():
            return _ok(inv, "", {"results": [], "count": 0, "query": query})

        matches = []
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(".") or item.name in ("__pycache__",):
                continue

            # Search in SKILL.md content
            md_path = item / "SKILL.md"
            skill_text = ""
            if md_path.is_file():
                try:
                    skill_text = md_path.read_text(encoding="utf-8").lower()
                except Exception:
                    pass

            # Search in skill.yaml
            yaml_path = item / "skill.yaml"
            yaml_text = ""
            if yaml_path.is_file():
                try:
                    yaml_text = yaml_path.read_text(encoding="utf-8").lower()
                except Exception:
                    pass

            combined = skill_text + " " + item.name.lower() + " " + yaml_text
            if query in combined:
                skill_info = {
                    "name": item.name,
                    "path": str(item.relative_to(ROOT)),
                    "description": "",
                    "status": "unknown",
                    "capabilities": [],
                }
                # Read skill.yaml for metadata
                if yaml_path.is_file():
                    try:
                        import yaml
                        with open(yaml_path, encoding="utf-8") as fy:
                            data = yaml.safe_load(fy)
                        if isinstance(data, dict):
                            skill_info["description"] = str(data.get("description") or data.get("display_name") or "")
                            skill_info["status"] = str(data.get("status", "unknown"))
                            skill_info["capabilities"] = [c.get("capability_id", "") for c in (data.get("capabilities") or []) if isinstance(c, dict)]
                    except Exception:
                        pass
                matches.append(skill_info)

            if len(matches) >= limit:
                break

        return _ok(inv, "", {"results": matches, "count": len(matches), "query": query})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_skill_create(inv: ToolInvocation) -> dict:
    """Create a new skill skeleton with SKILL.md and skill.yaml.

    Creates skills/<name>/ directory with template files.
    Status is set to pending_review — does NOT auto-enable.
    """
    args = inv.arguments
    name = str(args.get("name", "")).strip()
    description = str(args.get("description", "")).strip()
    capabilities = list(args.get("capabilities") or [])

    if not name:
        return _error_inv(inv, "name is required")

    # Sanitize skill name: only allow alphanumeric, hyphens, underscores
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    if not safe_name:
        return _error_inv(inv, "skill name must contain at least one valid character (a-z, 0-9, -, _)")

    skills_dir = ROOT / "skills"
    skill_dir = skills_dir / safe_name

    if skill_dir.exists():
        return _error_inv(inv, f"skill '{safe_name}' already exists")

    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=True, exist_ok=False)

        # Write SKILL.md template
        md_content = f"""# {safe_name}

{description or "A new agent skill."}

## Description

{description or "TODO: Write a detailed description of what this skill does."}

## Capabilities

"""
        if capabilities:
            for cap in capabilities:
                md_content += f"- {cap}\n"
        else:
            md_content += "- TODO: List capabilities\n"

        md_content += f"""
## Usage

TODO: Add usage examples and instructions.

## Status

pending_review
"""
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        # Write skill.yaml
        import yaml
        yaml_content = {
            "name": safe_name,
            "description": description or f"Skill: {safe_name}",
            "status": "pending_review",
            "version": "0.1.0",
            "capabilities": [{"capability_id": c} for c in capabilities] if capabilities else [],
        }
        with open(skill_dir / "skill.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(yaml_content, f, default_flow_style=False, allow_unicode=True)

        return _ok(inv, "", {
            "skill_name": safe_name,
            "skill_path": str(skill_dir.relative_to(ROOT)),
            "status": "pending_review",
            "message": f"Skill '{safe_name}' created with status=pending_review. Review and enable before use.",
        })
    except FileExistsError:
        return _error_inv(inv, f"skill '{safe_name}' already exists")
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_skill_install(inv: ToolInvocation) -> dict:
    """Install a skill from a local directory path or archive URL.

    Supports:
    - Local directory: copies the skill folder into skills/
    - URL (.zip/.tar.gz): downloads and extracts into skills/<name>/
    - Direct SKILL.md content: writes a minimal skill from markdown text

    Status is set to pending_review — does NOT auto-enable.
    """
    import shutil
    import tempfile
    import urllib.request
    import zipfile
    import tarfile

    args = inv.arguments
    source = str(args.get("source", "")).strip()
    skill_name = str(args.get("skill_name", "")).strip()

    if not source:
        return _error_inv(inv, "source is required (local path, URL, or SKILL.md content)")

    skills_dir = ROOT / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # ── Case 1: It's a markdown string (contains "# " or starts with markdown) ──
    if source.startswith("# ") or ("\n## " in source) or source.strip().startswith("```markdown"):
        if not skill_name:
            # Try to extract name from first heading
            match = re.match(r"^#\s+(.+)$", source, re.MULTILINE)
            skill_name = re.sub(r"[^a-zA-Z0-9_\-]", "", match.group(1).strip())[:40] if match else "installed_skill"
        name = skill_name
        skill_dir = skills_dir / name
        if skill_dir.exists():
            return _error_inv(inv, f"skill '{name}' already exists")
        try:
            skill_dir.mkdir(parents=True)
            # Clean markdown fences
            content = source
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n```\s*$", "", content)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
            _write_skill_yaml(skill_dir, name)
            return _ok(inv, "", {
                "skill_name": name, "skill_path": str(skill_dir.relative_to(ROOT)),
                "status": "pending_review", "method": "markdown",
                "message": f"Skill '{name}' installed from markdown. Review and enable before use.",
            })
        except Exception as e:
            return _error_inv(inv, str(e)[:200])

    # ── Case 2: Local directory path ──
    source_path = Path(source).expanduser().resolve()
    if source_path.is_dir():
        name = skill_name or source_path.name
        name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
        if not name:
            return _error_inv(inv, "invalid skill name after sanitization")
        target = skills_dir / name
        if target.exists():
            return _error_inv(inv, f"skill '{name}' already exists")
        try:
            shutil.copytree(str(source_path), str(target))
            if not (target / "SKILL.md").exists():
                return _error_inv(inv, "source directory must contain SKILL.md")
            _write_skill_yaml(target, name)
            return _ok(inv, "", {
                "skill_name": name, "skill_path": str(target.relative_to(ROOT)),
                "status": "pending_review", "method": "local_dir",
                "message": f"Skill '{name}' installed from directory. Review and enable before use.",
            })
        except Exception as e:
            return _error_inv(inv, str(e)[:200])

    # ── Case 3: URL download ──
    if source.startswith(("http://", "https://")):
        name = skill_name or source.rsplit("/", 1)[-1].split("?")[0].rsplit(".", 1)[0]
        name = re.sub(r"[^a-zA-Z0-9_\-]", "", name)[:40]
        if not name:
            return _error_inv(inv, "could not determine skill name from URL; provide skill_name")
        target = skills_dir / name
        if target.exists():
            return _error_inv(inv, f"skill '{name}' already exists")
        try:
            # Download to temp file
            with urllib.request.urlopen(source, timeout=30) as resp:
                data = resp.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
            tmp.write(data)
            tmp.close()

            # Extract based on extension
            target.mkdir(parents=True)
            if source.endswith(".zip") or source.endswith(".tar.gz") or source.endswith(".tgz"):
                if source.endswith(".zip"):
                    with zipfile.ZipFile(tmp.name, "r") as zf:
                        zf.extractall(str(target))
                else:
                    with tarfile.open(tmp.name, "r:gz") as tf:
                        tf.extractall(str(target))

                # If extracted to a subfolder, move contents up
                items = list(target.iterdir())
                if len(items) == 1 and items[0].is_dir() and (items[0] / "SKILL.md").exists():
                    inner = items[0]
                    for child in inner.iterdir():
                        shutil.move(str(child), str(target / child.name))
                    inner.rmdir()
            else:
                # Assume it's a single SKILL.md file
                (target / "SKILL.md").write_bytes(data)

            if not (target / "SKILL.md").exists():
                shutil.rmtree(str(target))
                return _error_inv(inv, "downloaded content does not contain SKILL.md")

            _write_skill_yaml(target, name)
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass
            return _ok(inv, "", {
                "skill_name": name, "skill_path": str(target.relative_to(ROOT)),
                "status": "pending_review", "method": "url",
                "message": f"Skill '{name}' installed from URL. Review and enable before use.",
            })
        except Exception as e:
            try:
                if target.exists():
                    shutil.rmtree(str(target))
            except Exception:
                pass
            return _error_inv(inv, f"install failed: {str(e)[:200]}")

    return _error_inv(inv, f"unsupported source type: {source[:80]}")


def _write_skill_yaml(skill_dir: Path, name: str) -> None:
    """Write a minimal skill.yaml for an installed skill."""
    import yaml
    yaml_path = skill_dir / "skill.yaml"
    if yaml_path.exists():
        return
    yaml_content = {
        "name": name,
        "description": f"Skill: {name}",
        "status": "pending_review",
        "version": "0.1.0",
        "capabilities": [],
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_content, f, default_flow_style=False, allow_unicode=True)


def handle_skill_inspect(inv: ToolInvocation) -> dict:
    """Read and return a skill's SKILL.md content without loading it."""
    args = inv.arguments
    skill_name = str(args.get("skill_name", "")).strip()

    if not skill_name:
        return _error_inv(inv, "skill_name is required")

    # Sanitize
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "", skill_name)
    if not safe_name:
        return _error_inv(inv, f"invalid skill_name: {skill_name}")

    skills_dir = ROOT / "skills"
    skill_dir = skills_dir / safe_name
    md_path = skill_dir / "SKILL.md"

    if not skill_dir.is_dir():
        return _error_inv(inv, f"skill '{safe_name}' not found")

    try:
        yaml_path = skill_dir / "skill.yaml"
        yaml_data = {}
        if yaml_path.is_file():
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        content = ""
        if md_path.is_file():
            content = md_path.read_text(encoding="utf-8")

        return _ok(inv, "", {
            "skill_name": safe_name,
            "skill_path": str(skill_dir.relative_to(ROOT)),
            "content": content,
            "content_length": len(content),
            "status": yaml_data.get("status", "unknown"),
            "description": yaml_data.get("description", ""),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_skill_list', 'handle_skill_request_load', 'handle_skill_load', 'handle_skill_find', 'handle_skill_create', 'handle_skill_inspect']
