# agent/modules/cmdb/capability.py
"""Capability manifest for CMDB — enabled, LLM-callable."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_CMDB = CapabilityManifest(
    capability_id="cmdb",
    name="CMDB",
    status="enabled",
    description="设备资产清单管理。可查询、添加、删除网络设备资产，每个资产可一键连接终端。",
    module=CapabilityModuleSpec(
        module_id="cmdb",
        status="enabled",
        service_path="agent.modules.cmdb.service",
        operations=["list_assets", "get_asset", "add_asset", "delete_asset"],
        description="设备资产 CRUD 操作。",
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="cmdb",
            status="enabled",
            related_tools=[
                "cmdb.list_assets",
                "cmdb.get_asset",
                "cmdb.add_asset",
            ],
            intent_patterns=[
                "查资产", "列出设备", "设备列表", "资产管理",
                "cmdb", "asset list", "有哪些设备", "设备清单",
                "添加设备", "录入设备", "新增设备",
            ],
            required_inputs=[],
            prompt_summary=(
                "查询 CMDB 中的设备资产。列出/获取设备信息（名称、类型、厂商、型号、IP、连接方式）。"
                "添加设备需提供主机地址。不可伪造资产记录。"
            ),
            preconditions=["workspace 已初始化。"],
            postconditions=["返回的设备信息来自持久化存储。"],
            safety_rules=[
                "不可声明 CMDB 中存在未从工具返回的设备。",
                "不可伪造或推断资产信息。",
                "添加设备 API 走审批流（可能需人工确认）。",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="cmdb.list_assets",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.cmdb.tools:tool_list_assets",
            description="列出当前 workspace 中所有设备资产（名称/类型/厂商/型号/IP/协议/端口/用户）。",
        ),
        CapabilityToolRef(
            tool_id="cmdb.get_asset",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.cmdb.tools:tool_get_asset",
            description="获取指定设备资产的完整信息。",
        ),
        CapabilityToolRef(
            tool_id="cmdb.add_asset",
            status="enabled",
            callable_by_llm=True,
            risk_level="medium",
            requires_approval=True,
            forbidden=False,
            handler_ref="agent.modules.cmdb.tools:tool_add_asset",
            description="添加设备资产到 CMDB（需审批）。提供设备名/主机/端口/协议/厂商/用户名/密码。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="asset_records",
            output_type="asset_records",
            description="设备资产记录列表。",
            artifact_type="cmdb_assets",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=True,
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=False,
        requires_human_review=False,
        notes="读操作无风险。添加操作需审批。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
