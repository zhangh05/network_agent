# agent/modules/remote/capability.py
"""Capability manifest for Remote Device Access (SSH/Telnet)."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_REMOTE = CapabilityManifest(
    capability_id="network_device",
    name="Remote Access (SSH/Telnet)",
    status="enabled",
    description="SSH / Telnet 远程连接到任何主机（网络设备、Linux 服务器、Windows 终端等），执行命令并返回结果。危险命令自动拦截。",
    intent_patterns=[
        "SSH 登录", "Telnet 登录", "连接设备", "远程执行命令",
        "show run", "show version", "display version", "uname", "df", "free",
        "远程服务器", "SSH 服务器", "登录 Linux", "执行命令",
    ],
    prompt_summary=(
        "SSH/Telnet 通用远程终端。直接连接任何可达主机（网络设备/服务器/VM），"
        "一次性 connect→exec→disconnect，无状态。凭据可从 CMDB 获取或由用户直接提供。"
        "危险命令自动拦截。Telnet 无加密，仅内网使用。"
    ),
    module=CapabilityModuleSpec(
        module_id="remote",
        status="enabled",
        service_path="agent.modules.remote.service",
        operations=["connect_device", "ssh_connect", "telnet_connect"],
        description="SSH/Telnet 远程设备连接与命令执行。",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="network.ssh",
            status="enabled",
            callable_by_llm=True,
            risk_level="medium",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_network_ssh",
            description="SSH 登录设备，执行一条命令后立即断开。危险命令自动拦截，无需审批。",
        ),
        CapabilityToolRef(
            tool_id="network.telnet",
            status="enabled",
            callable_by_llm=True,
            risk_level="medium",
            requires_approval=False,
            forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_network_telnet",
            description="Telnet 登录设备，执行一条命令后立即断开。无加密，仅在内网使用。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="command_output",
            output_type="command_output",
            description="设备命令执行结果（文本）。",
            artifact_type="device_output",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=True,
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=True,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=False,
        requires_human_review=True,
        notes="真实设备访问已启用。危险命令（reload/erase/format）运行时自动拦截。",
    ),
    dependencies=["cmdb"],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
