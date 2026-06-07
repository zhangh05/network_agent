# Runtime Archive v0.1

> **Status**: Implemented — `2002069`  
> **Module**: `runtime/archive.py`

## Purpose

Safe, auditable archival of expired run/trace/job/temp data from active workspace directories to `workspace/<id>/archives/YYYY-MM/`.

## Key Principles

1. **Default is dry-run** — never moves files without explicit confirmation.
2. **True archive requires `confirm=True`** — safety guard against accidental archival.
3. **Never archives active references** — workspace state, current artifacts, recent runs.
4. **Never deletes** — files are moved, not removed. No permanent data loss.
5. **Audited** — every archive operation writes to `workspace/<id>/runtime_audits/archive_<id>.json`.
6. **No cron** — v0.1 is manual-only. No scheduled automation.

## Archive Policy

| Type | Threshold | Notes |
|------|-----------|-------|
| runs | >30d, over keep_latest(500) | Not active refs |
| traces | >30d, over keep_latest(1000) | |
| jobs | >30d, status=succeeded/failed/cancelled | Not running/queued |
| temp | >7d | |
| artifacts | temp/quarantine only | Not active refs, not other lifecycles |
| reports | never archived | |

## Archive Directory Structure

```
workspace/<id>/archives/YYYY-MM/
  runs/
  traces/
  jobs/
  temp/
  artifacts/
```

## Dry-Run / Confirm Rules

| Invocation | Result |
|------------|--------|
| `preview_archive_candidates()` | Preview only, never moves |
| `apply_archive()` | dry_run=True, preview only |
| `apply_archive(dry_run=False, confirm=False)` | BLOCKED |
| `apply_archive(dry_run=False, confirm=True)` | Actual move executed |

## Path Boundary Safety

Uses `Path.resolve().relative_to()` — NOT string startswith.
This prevents `/workspace/default2` from passing `/workspace/default` checks,
path traversal (`../../../`), and symlink escape.

## Audit Records

Written to: `workspace/<id>/runtime_audits/archive_<id>.json`

Contains:
- audit_id, type: archive, created_at, workspace_id
- dry_run, confirmed, policy
- candidate_counts, moved_counts, blocked_count
- warnings

Prohibited:
- absolute paths, keys, tokens, passwords, communities
- full source_config, full deployable_config, full prompt

## API

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/workspaces/<id>/archive/preview` | Preview candidates |
| POST | `/api/workspaces/<id>/archive/apply` | Apply archive (dry_run default) |
| GET | `/api/workspaces/<id>/archive/audits` | List audits |
| GET | `/api/workspaces/<id>/archive/audits/<aid>` | Audit detail |

All APIs: no absolute paths, no secrets, workspace_id validated.

## UI

- Archive candidate count badge in dashboard runtime status panel
- Yellow = candidates exist, Green = none
- No default archive button

## Security Red Lines

1. Never default delete/archive
2. Never archive active refs
3. Never bypass workspace boundary
4. Never expose absolute paths
5. Never expose secrets
6. No real device execution
7. No SSH/Telnet/SNMP/nmap
8. No arbitrary shell
9. No config push
