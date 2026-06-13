# Skill Template

## Structure
```
skills/<name>/
  SKILL.md       — LLM-visible instructions
  skill.yaml     — metadata (optional, preferred)
  adapter.py     — legacy adapter (optional)
```

## SKILL.md

```markdown
# Skill: My Feature

## When to Use
Use this skill when the user asks to:
- Do something specific
- Perform a particular operation
- Analyze certain data

## What It Needs
- Required input: input_data (string)
- Optional: config_options (object)

## Preconditions
- Workspace must be active
- User must have appropriate permissions

## Postconditions
- Result is saved as an artifact
- Review item is created if needed

## Safety Rules
- Do not access real network devices
- Do not modify production configurations
- Always cite sources
```

## skill.yaml

```yaml
skill_id: my_feature_skill
name: My Feature
version: "0.1.0"
status: planned
description: >-
  Skill for performing my feature operations.

related_tools:
  - my_feature.run

intent_patterns:
  - do my feature
  - run my feature
  - my feature operation

required_inputs:
  - input_data

preconditions:
  - workspace_active

postconditions:
  - result_saved

safety_rules:
  - no_real_device_access
  - no_config_push
```

## adapter.py (optional, legacy)

```python
# skills/my_feature/adapter.py
# Legacy adapter for backward compatibility.
# New skills should use skill.yaml instead.

class MyFeatureAdapter:
    def get_instructions(self) -> str:
        return "When the user asks to do my feature..."
```
