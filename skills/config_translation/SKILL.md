# Config Translation Skill

## Status

- Skill registry: enabled
- Module: `config_translation`
- Entrypoint: `POST /api/modules/config-translation/translate`

## When To Use

Use this skill when the user asks to translate network device configuration across vendors, for example Cisco to Huawei or Huawei to H3C.

## Input

Required:

- `source_config`
- `source_vendor`
- `target_vendor`

Optional:

- `source_domain`
- `target_domain`
- `source_platform`
- `target_platform`

## Output

- `deployable_config`: deterministic translation output
- `manual_review`: items requiring human verification
- `semantic_near`: similar but not directly deployable candidates
- `unsupported`: content that cannot be translated safely
- `audit`: safety and consistency checks

## Rules

- Do not modify `deployable_config`.
- Do not treat full raw output as deployable.
- Always surface `manual_review`.
- Never hide high-risk ACL, policy, QoS, BGP neighbor, password, key, or SNMP items.
- Do not call an LLM translation path from inside this skill.
- Do not claim production config push.
