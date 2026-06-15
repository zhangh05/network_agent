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
        req_path = WS_ROOT / ws / "skill_requests.jsonl"
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
            session_meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
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
