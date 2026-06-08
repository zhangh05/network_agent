# Tool Runtime General Tools v0.2

## Overview

Network Agent v0.2 introduces 48 new general-purpose tools for the Agent platform, bringing the total tool count to **55** (up from **7** in v0.1).

## Design Principles

- **No arbitrary shell execution** — all command execution goes through allowlisted `command_id`
- **No arbitrary file access** — workspace file tools validate paths and block traversal
- **No real device access** — SSH/Telnet/SNMP/Nmap remain forbidden
- **No config push** — config push is forbidden at policy level
- **Read-only by default** — most tools are low-risk and read-only
- **Approval gates for high risk** — `command.approved_exec` and `powershell.approved_script` require `approval_id`

## Tool Count by Category (55 total)

| Category | Count | Risk |
|----------|-------|------|
| artifact | 7 | low/medium |
| parser | 3 | low |
| report | 6 | low/medium |
| command | 2 | low/high |
| knowledge | 6 | low/medium |
| web | 5 | low/medium |
| session | 7 | low/medium |
| runtime | 5 | low |
| text | 8 | low |
| workspace | 5 | low/medium |
| powershell | 1 | high |

**Total: 55**

## Tool List

### Artifact (7)
- `artifact.list` — List workspace artifacts (low)
- `artifact.read_summary` — Read artifact summary (low)
- `artifact.search` — Search artifacts by query (low)
- `artifact.read_content_safe` — Read safe preview (low)
- `artifact.save_result` — Save tool result as artifact (medium)
- `artifact.tag` — Add tags to artifact (low)
- `artifact.delete_soft` — Soft-delete artifact (medium)

### Parser (3)
- `parser.parse_config_text` — Parse config text (low)
- `parser.extract_interfaces` — Extract interfaces (low)
- `parser.extract_routes` — Extract routes (low)

### Report (6)
- `report.render_from_safe_summary` — Render from safe summary (low)
- `report.render_markdown` — Render markdown (low)
- `report.save_artifact` — Save report as artifact (medium)
- `doc.render_from_safe_summary` — Render doc from safe summary (low)
- `table.render_markdown` — Render table as markdown (low)
- `diagram.render_mermaid` — Output Mermaid diagram text (low)

### Command (2)
- `command.dry_run_echo` — Test dry-run pipeline (low)
- `command.approved_exec` — Execute allowlisted command (high, disabled, requires approval)

### Knowledge (6)
- `knowledge.index_artifact` — Index artifact (medium)
- `knowledge.reindex` — Reindex source (medium)
- `knowledge.search` — Search knowledge base (low)
- `knowledge.get_source` — Get source metadata (low)
- `knowledge.get_chunk_summary` — Get chunk summary (low)
- `knowledge.explain_not_found` — Explain no results (low)

### Web (5)
- `web.search` — Search public web (medium)
- `web.fetch_summary` — Fetch page summary (medium)
- `web.official_doc_search` — Vendor doc URLs (low)
- `web.extract_links` — Extract links (medium)
- `web.save_to_artifact` — Save as artifact (medium)

### Session (7)
- `session.list` — List sessions (low)
- `session.get_summary` — Session summary (low)
- `session.create` — Create session (medium)
- `session.archive` — Archive session (medium)
- `run.list_recent` — Recent runs (low)
- `run.get_summary` — Run summary (low)
- `memory.search` — Memory search (low)

### Runtime (5)
- `runtime.health` — Health check (low)
- `runtime.selfcheck` — Self check (low)
- `runtime.diagnostics` — Diagnostics report (low)
- `runtime.retention_preview` — Retention preview (low)
- `runtime.archive_preview` — Archive preview (low)

### Text (8)
- `text.redact` — Redact sensitive text (low)
- `text.diff` — Compute text diff (low)
- `text.extract_keywords` — Extract keywords (low)
- `text.classify` — Classify text (low)
- `json.validate` — Validate JSON (low)
- `yaml.validate` — Validate YAML (low)
- `csv.summarize` — Summarize CSV (low)
- `table.extract` — Extract table (low)

### Workspace (5)
- `workspace.list_files` — List files (low)
- `workspace.read_text_preview` — Read preview (low)
- `workspace.write_artifact_file` — Write file (medium)
- `workspace.path_exists` — Check path (low)
- `workspace.get_metadata` — Get metadata (low)

### PowerShell (1)
- `powershell.approved_script` — Execute allowlisted script (high, disabled, requires approval)

## Risk Level Policy

| Risk | Default | Approval | dry_run | Notes |
|------|---------|----------|---------|-------|
| low | allowed | no | supported | Read-only, safe |
| medium | allowed | configurable | supported | Writes artifact only |
| high | disabled | required | default on | Only allowlisted command_id/script_id |

## Forbidden Tools (12)

The following tool IDs are permanently forbidden at policy level:
```
shell.exec, powershell.exec, command.exec, ssh.exec, telnet.exec,
snmp.walk, nmap.scan, ping.sweep, config.push, file.read_any,
file.write_any
```

## API

- `GET /api/tools/catalog` — Read-only tool catalog (metadata only, no invoke)
- No `/api/tools/invoke` endpoint exists
- No Tool Invoke UI

## Web Safety

- Private IP ranges blocked: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8
- localhost blocked
- No login-state capture
- No command execution from web content
- All results include source refs

## Workspace File Safety

- Path traversal (`..`) sanitized
- `Path.resolve()` validated within workspace root
- File reads limited to 1MB
- Writes restricted to workspace/output directory

## Knowledge Safety

- Only `safe_excerpt` and `summary` returned
- No full artifact content
- No full config
- No absolute paths
- Sensitive/confidential artifacts excluded

## Tests

- `test_tool_runtime_general_tools_v02.py` — 24 tests
- `test_tool_runtime_catalog_v021.py` — 13 tests
- `test_tool_runtime_client_integration_v021.py` — 21 tests
- Total: **58** tool-specific tests
