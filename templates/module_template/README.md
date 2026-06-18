# Module Template

## Structure
```
agent/modules/<name>/
  capability.py
  tools.py
  service.py
  __init__.py
```

## capability.py

```python
# agent/modules/my_feature/capability.py
from agent.capabilities.schemas import (
    CapabilityManifest, CapabilityModuleSpec,
    CapabilitySkillSpec, CapabilityToolRef,
    CapabilityOutputSpec, CapabilitySafetySpec,
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
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="my_feature_skill",
            status="planned",
            intent_patterns=["do my feature"],
            required_inputs=["input_data"],
            safety_rules=["Do not access real devices"],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="my_feature.run",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            handler_ref="agent.modules.my_feature.tools.tool_handler",
            description="Run my feature",
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

## tools.py

```python
# agent/modules/my_feature/tools.py
from tool_runtime.schemas import ToolSpec, ToolInvocation

TOOL_MY_FEATURE = ToolSpec(
    tool_id="my_feature.run",
    name="My Feature",
    description="Run my feature tool",
    category="my_feature",
    risk_level="low",
    input_schema={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Input data"},
        },
        "required": ["input"],
    },
    requires_approval=False,
    callable_by_llm=True,
    enabled=False,  # False until capability is enabled
)

def tool_handler(inv: ToolInvocation) -> dict:
    args = inv.arguments
    input_data = args.get("input", "")

    try:
        from agent.modules.my_feature.service import run_feature
        result = run_feature(input_data)
        return {
            "ok": True,
            "summary": "Feature executed",
            "data": result,
        }
    except Exception as e:
        return {
            "ok": False,
            "summary": str(e)[:200],
            "errors": [str(e)[:200]],
        }
```

## service.py

```python
# agent/modules/my_feature/service.py
"""Business logic for My Feature module."""

def run_feature(input_data: str) -> dict:
    """Core business logic.
    
    This function knows nothing about LLM, ToolRouter, or Skills.
    """
    # ... implementation ...
    return {"processed": True, "output": f"Processed: {input_data}"}
```

## __init__.py

```python
# agent/modules/my_feature/__init__.py
# My Feature capability module
```
