# agent/modules/pcap/capability.py
"""Capability manifest for PCAP Analysis."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_PCAP = CapabilityManifest(
    capability_id="pcap_analysis",
    name="PCAP 报文分析",
    status="enabled",
    description="解析 PCAP 文件，提取会话信息、五元组过滤、TCP 流对齐。支持从 workspace 文件或 file_id 读取。",
    intent_patterns=[
        "分析 PCAP", "解析报文", "抓包分析", "报文分析",
        "pcap analysis", "PCAP 文件", "流量分析",
        "TCP 流", "五元组过滤", "tcp stream",
    ],
    prompt_summary=(
        "解析 PCAP 文件获取报文信息。"
        "支持按五元组（src/sport/dst/dport）过滤、TCP 流对齐、连接分组。"
        "需提供 workspace 中的 PCAP 文件路径或 file_id。"
    ),
    module=CapabilityModuleSpec(
        module_id="pcap",
        status="enabled",
        service_path="agent.modules.pcap.service",
        operations=["parse_pcap_file", "get_session", "filter_by_5tuple"],
        description="PCAP 报文解析与会话管理。",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="pcap.analysis.run",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_pcap_analysis_run",
            description="PCAP 分析统一入口。支持上传 PCAP 文件、查看会话、按五元组过滤、TCP 流对齐。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="pcap_analysis_result",
            output_type="pcap_analysis_result",
            description="PCAP 分析结果（报文统计、连接分组、过滤结果）。",
            artifact_type="pcap_result",
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
        notes="仅分析本地 PCAP 文件，不涉及真实设备操作。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
