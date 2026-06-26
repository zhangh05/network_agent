# agent/modules/cmdb/capability.py
"""Capability manifest for CMDB — enabled, LLM-callable."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_CMDB = CapabilityManifest(
    capability_id="cmdb",
    name="CMDB",
    status="enabled",
    description="设备资产清单管理。可查询、添加、删除网络设备资产，每个资产可一键连接终端。",
    intent_patterns=[
        "CMDB", "资产列表", "设备资产", "设备清单",
        "添加设备", "删除设备", "编辑设备", "查看资产",
        "network asset", "device inventory",
    ],
    prompt_summary=(
        "CMDB 设备资产管理。列出所有网络设备（含主机/IP/端口/型号/区域/凭据），"
        "支持添加、删除、按区域或类型筛选。凭据仅用于连接，不输出到回复中。"
    ),
    module=CapabilityModuleSpec(
        module_id="cmdb",
        status="enabled",
        service_path="agent.modules.cmdb.service",
        operations=["list_assets", "get_asset", "save_asset", "delete_asset"],
        description="CMDB 设备资产管理与统计。",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="device.list",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_cmdb_list_assets",
            description="列出所有设备资产，支持按类型/厂商/区域筛选和模糊搜索。",
        ),
        CapabilityToolRef(
            tool_id="device.get",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_cmdb_get_asset",
            description="获取单个设备资产详情，含主机/IP/端口/协议/用户名/密码/区域/位置。",
        ),
        CapabilityToolRef(
            tool_id="device.add",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_cmdb_add_asset",
            description="添加新设备资产。需提供名称、主机地址、类型、厂商、协议等。",
        ),
        CapabilityToolRef(
            tool_id="device.delete",
            status="enabled",
            callable_by_llm=True,
            risk_level="medium",
            requires_approval=True,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_cmdb_delete_asset",
            description="删除设备资产（软删除，可恢复）。需确认后执行。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="cmdb_asset_list",
            output_type="cmdb_asset_list",
            description="设备资产列表或详细信息的结构化输出。",
            artifact_type="cmdb_result",
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
        notes="仅资产元数据管理，不涉及设备操作。删除需用户确认。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
