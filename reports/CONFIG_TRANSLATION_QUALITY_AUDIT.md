# Config Translation Quality Audit v0.1

- **Timestamp**: 2026-06-07
- **Commit**: 8309b3b (pre-audit baseline)
- **Test baseline**: 790 passed, 7 skipped, 0 failed

## Source Residue Diagnosis

Source residue occurs when source-vendor syntax or tokens remain in target output.

### Confirmed Residue Cases

| # | Source Vendor → Target | Pattern | Severity |
|---|------------------------|---------|----------|
| 1 | Cisco → Huawei | `GigabitEthernetX/X/X` interface name not converted to Comware format | high |
| 2 | Cisco → Huawei | Cisco keywords (`gigabitethernet`, `switchport`, etc.) in Comware output | medium |
| 3 | Comware → Cisco | Comware keywords (`sysname`, `vlan batch`, `undo`) in Cisco output | high |

### Residue Fix Strategy

- `DeployablePolicy._is_source_residue()` already catches cross-vendor keyword leakage
- `QualityAuditor.check_source_residue()` adds post-translation residue detection in deployable output
- Residue items are tracked in `quality_summary.source_residue_items` with severity
- Gates field `residue` is wired to actual count

## Silent-Drop Diagnosis

Silent-drop occurs when meaningful source lines have no appearance in any output layer.

### Silent-Drop Categories

| Category | Lines | Handling |
|----------|-------|----------|
| Untranslated but meaningful | `hostname`, `router ospf`, `no shutdown` | Flagged in quality_summary |
| Security-sensitive | `access-list`, `ip route`, `snmp-server community` | Critical severity, must not be silent-dropped |
| Same-vendor pass-through | `description` | Passed through but provenance tracked |
| Safe drop | blank lines, comments, `end`, `exit` | Safely ignored, tracked in safe_dropped_lines |

### Silent-Drop Fix Strategy

- `QualityAuditor` tracks all source lines and their classification
- `QualityAuditor.find_silent_drops()` identifies lines with no output layer assignment
- Security-sensitive lines are NEVER classified as safe-drop
- Accounted lines are tracked by output layer (deployable, manual_review, unsupported, semantic_near)
- Silent-drop count wired to `audit.gates.silent_drop`

## Quality Summary Structure

Added `quality_summary` field to `TranslateResponse.as_dict()`:

| Field | Type | Description |
|-------|------|-------------|
| `source_residue_count` | int | Number of source vendor residue items detected |
| `silent_drop_count` | int | Number of meaningful lines not in any output layer |
| `unsupported_count` | int | Lines classified as unsupported |
| `safe_drop_count` | int | Lines safely ignored (comments, blanks, display-only) |
| `review_required_count` | int | Lines requiring manual review |
| `deployable_count` | int | Lines classified as deployable |
| `semantic_near_count` | int | Semantic-near translations |
| `total_source_lines` | int | Total lines in source config |
| `meaningful_source_lines` | int | Lines with semantic content |
| `source_residue_items` | list | Detailed residue items (max 20) |
| `silent_drop_items` | list | Detailed silent-drop items (max 20) |
| `safe_dropped_lines` | list | Safely dropped lines (max 20) |
| `unconverted_items` | list | Items not converted to any layer (max 20) |
| `warnings` | list | Quality warnings (max 20) |

## Gates Wiring

Previously hardcoded to all-zeros, now wired:

| Gate | Before | After |
|------|--------|-------|
| `silent_drop` | 0 (hardcoded) | Real count from QualityAuditor |
| `residue` | 0 (hardcoded) | Real count from QualityAuditor |
| `secret_leak` | 0 | 0 (DeployablePolicy handles secrets) |
| `high_risk_deployable` | 0 | 0 (DeployablePolicy blocks high-risk) |
| `default_any` | 0 | 0 (DeployablePolicy blocks default-any) |
| `auto_vendor_uncertain` | 0 | 0 |

## Test Coverage

40 tests in `harness/test_config_translation_quality_hardening.py`:

| Class | Tests | Coverage |
|-------|-------|----------|
| TestSourceResidue | 5 | Detection, manual_review, risk, same-vendor, exit |
| TestSilentDrop | 5 | Detection, tracking, quality_summary, unconverted, gates |
| TestSecuritySensitiveLines | 6 | ACL, NAT, static route, SNMP, password, shutdown |
| TestSafeDrop | 5 | Blanks, comments, end/exit, banner, security exclusion |
| TestQualitySummary | 5 | Existence, residue count, silent count, safe count, gates |
| TestKnownIssues | 3 | Cisco→Huawei interface, static route, hostname |
| TestAPIContract | 5 | Translate API, main chain, no LLM, MR visibility, risk |
| TestQualityAuditor | 6 | Create, classify empty/comment/security/meaningful, summary |

## Non-Goals

- Not a rewrite of translate_bundle
- No LLM involvement in deployable_config
- No new business modules
- No real device execution

## Conclusion

**Config Translation Quality Hardening: PASS**

- Source residue detection: active
- Silent-drop accounting: active
- Quality summary: generated and returned
- Gates: wired to real values
- Security-sensitive lines: never safe-dropped
- 40 new quality tests: all passing
