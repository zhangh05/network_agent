# Config Translation Skill

## Status

- Skill registry: enabled
- Module: `config_translation`
- Entrypoint: `POST /api/modules/config-translation/translate`

## When To Use

Use this skill when the user asks to translate network device configuration across vendors, for example Cisco to Huawei or Huawei to H3C.

## Input

Provide EITHER `filepath` (preferred for large configs) OR `source_config`:

- `filepath` (str, preferred): workspace-relative path to the config file. Use this when the user has uploaded a config file (e.g., via the chat upload). After reading the file with workspace.file.read, pass the same path here.
- `source_config` (str): raw config text. Only use for short inline configs, not for files.
- `source_vendor` (str): vendor hint, default "auto"
- `target_vendor` (str): target vendor, default "huawei"
- `workspace_id` (str, optional): workspace ID, default "default"

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
