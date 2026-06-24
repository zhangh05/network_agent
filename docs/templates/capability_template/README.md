# Capability Template

## Structure
```
agent/modules/<name>/
  capability.py    — CapabilityManifest
  tools.py         — ToolSpec + handlers
  service.py       — business logic
  __init__.py
```

## Registration
1. Add to `agent/capabilities/builtin.py`
2. Set status: `planned` then `enabled`
3. Run `python3 scripts/inspect_runtime_tools.py` to verify

## CapabilityManifest Template

```python
from agent.capabilities.schemas import (
    CapabilityManifest, CapabilityModuleSpec, CapabilitySkillSpec,
    CapabilityToolRef, CapabilityOutputSpec, CapabilitySafetySpec
)

CAPABILITY_MY_FEATURE = CapabilityManifest(
    capability_id="my_feature",
    name="My Feature",
    status="planned",
    description="Description of what this capability does",
    module=CapabilityModuleSpec(
        module_id="my_feature",
        status="planned",
        service_path="agent.modules.my_feature.service",
        operations=["run"],
        description="My Feature module",
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="my_feature_skill",
            status="planned",
            intent_patterns=["do my feature"],
            required_inputs=["input_data"],
            safety_rules=["Do not access real devices"],
            prompt_summary="When the user asks to do my feature...",
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="my_feature.run",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            handler_ref="agent.modules.my_feature.tools.tool_handler",
            description="Run my feature tool",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="my_feature_result",
            output_type="result",
            artifact_type="my_feature_result",
            sensitivity="internal",
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
    ),
)
```
