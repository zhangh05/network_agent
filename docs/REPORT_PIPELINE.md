# Report Pipeline

## Report as Artifact

All reports are stored as Artifacts with `artifact_type=report`. Reports go through the standard File Pipeline: upload/classify/policy/store/index/access.

## Supported Formats

| Format | Status |
|--------|--------|
| Markdown (`.md`) | Supported |
| HTML (`.html`) | Supported |
| JSON (`.json`) | Supported |
| CSV (`.csv`) | Supported |
| DOCX (`.docx`) | Skeleton — unsupported, honest response |
| PDF (`.pdf`) | Skeleton — unsupported, honest response |

Unsupported formats return explicit "not supported" — no fake success.

## Config Translation Report Sections

| Section | Content |
|---------|---------|
| Run info | Run ID, timestamps, duration, status |
| Input summary | Safe summary of source config (no full config) |
| Output summary | Safe summary of translated config (no full config) |
| Manual review | Items flagged for human review |
| Semantic near | Items semantically close but needing verification |
| Unsupported | Unsupported config directives |
| Audit | Audit trail of translation decisions |
| Artifact refs | References to input/output config artifacts |
| Verification | Verification results (pass/fail/details) |
| LLM participation | Whether LLM participated in translation |
| Security note | Security disclaimers and notes |

## Deployable Config Policy

- Default: `include_deployable_config=false`
  - Report does NOT contain deployable configuration content
  - Report sensitivity = `internal`
- When `include_deployable_config=true`:
  - Report contains deployable configuration
  - Report sensitivity = `sensitive`
  - Access gated by sensitivity policy

## Sensitivity Rules

| Condition | Sensitivity |
|-----------|-------------|
| Normal report (no deployable config) | `internal` |
| Report with deployable config | `sensitive` |
| Report with secrets detected | `secret` |

## Access Control

| Rule | Behavior |
|------|----------|
| Sensitive report (default) | Metadata only; content blocked |
| Sensitive report with `allow_sensitive=true` | Full content returned |
| All reports in Memory | Summary only (no full content) |
| All reports in Trace | Metadata only (no content) |
| All reports in LLM context | Summary only (no full content) |

## Report Storage

Reports saved via `ArtifactStore.save_artifact()`:
- `artifact_type=report`
- `scope=workspace` (persists beyond single run)
- Indexed in `artifacts.index.json`
