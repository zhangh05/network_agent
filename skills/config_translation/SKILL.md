# Config Translation Skill

## When to Use

Use this skill when the user requests:
- Configuration migration ("帮我把 Cisco 配置转成华为")
- Vendor translation ("翻译网络配置")
- Cross-vendor conversion

Input: Cisco / Huawei / H3C / Ruijie device configuration text.

## How to Call

```
POST /api/translate
```

Required fields:
| Field | Type | Description |
|-------|------|-------------|
| source_config | string | Full source device configuration text |
| source_vendor | string | Source vendor: cisco / huawei / h3c / ruijie |
| target_vendor | string | Target vendor: cisco / huawei / h3c / ruijie |

Optional fields:
| Field | Type | Description |
|-------|------|-------------|
| source_domain | string | Source domain: auto / routing / switching / firewall |
| target_domain | string | Target domain |
| source_platform | string | Source platform: auto / vrp / ios / comware |
| target_platform | string | Target platform |

## How to Interpret Output

| Field | Meaning |
|-------|---------|
| deployable_config | Deterministic translation output — safe to deploy |
| manual_review | Items requiring human verification before deployment |
| semantic_near | Semantically similar but NOT auto-deployable |
| unsupported | Cannot be translated — NOT silently dropped |
| audit | Safety, consistency, and gate checks |

## Red Lines (NEVER Violate)

1. **do_not_modify_deployable_config** — Never alter the translated output
2. **do_not_use_full_output_as_deployable** — Only `deployable_config` field is authoritative
3. **always_check_manual_review** — If non-empty, warn user before deployment
4. **never_hide_high_risk** — ACL, Policy, QoS, BGP neighbor, password items must remain in manual_review
5. **do_not_bypass_translate_bundle** — translator_entry must be `translate_bundle`
6. **do_not_call_graph_agent** — Never invoke GraphAgent or LLM translation path

## Response Guidance

- If `manual_review` is non-empty: prompt user to check the review tab
- If `unsupported` is non-empty: list unsupported reasons
- If safety gate fails: refuse to produce a deployable conclusion
- When user asks "just the final config": still distinguish deployable from review candidates
- BGP passwords / SNMP communities: must appear in manual_review (not deployable)
