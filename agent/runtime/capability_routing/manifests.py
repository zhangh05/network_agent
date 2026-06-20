# agent/runtime/capability_routing/manifests.py
"""Built-in capability and module manifests.

The project is moving away from tool-first execution. These manifests define
business capabilities first, then map each capability to a small tool set and
module services.
"""

from __future__ import annotations

from .models import CapabilityPackage, ModuleServiceManifest


MODULE_MANIFESTS: dict[str, ModuleServiceManifest] = {
    "workspace": ModuleServiceManifest(
        module_id="workspace",
        package="tool_runtime.general_tools.file_tools",
        service_path="tool_runtime.general_tools.file_tools",
        operations=("read", "preview", "write_artifact"),
    ),
    "knowledge": ModuleServiceManifest(
        module_id="knowledge",
        package="agent.modules.knowledge",
        service_path="agent.modules.knowledge.service",
        operations=("search", "read", "index"),
    ),
    "memory": ModuleServiceManifest(
        module_id="memory",
        package="memory",
        service_path="memory.service",
        operations=("search", "list", "profile"),
    ),
    "config_translation": ModuleServiceManifest(
        module_id="config_translation",
        package="agent.modules.config_translation",
        service_path="agent.modules.config_translation.service",
        operations=("translate", "parse", "diff"),
        kind="business",
    ),
    "config_analysis": ModuleServiceManifest(
        module_id="config_analysis",
        package="agent.modules.config_analysis",
        service_path="agent.modules.config_analysis.service",
        operations=("parse", "translate", "extract_interfaces", "extract_routes", "diff", "summarize"),
        kind="business",
    ),
    "pcap_analysis": ModuleServiceManifest(
        module_id="pcap_analysis",
        package="agent.modules.pcap",
        service_path="agent.modules.pcap.service",
        operations=("parse", "session", "filter", "align"),
        kind="business",
    ),
    "report": ModuleServiceManifest(
        module_id="report",
        package="agent.modules.report",
        service_path="agent.modules.report.service",
        operations=("draft", "render", "save"),
    ),
    "runtime": ModuleServiceManifest(
        module_id="runtime",
        package="agent.runtime",
        service_path="agent.runtime.service",
        operations=("health", "diagnostics", "trace"),
    ),
}


CAPABILITY_PACKAGES: tuple[CapabilityPackage, ...] = (
    CapabilityPackage(
        capability_id="workspace_read",
        display_name="Workspace Read",
        description="Read or inspect workspace files and artifacts.",
        intent_keywords=("file", "workspace", "artifact", "文件", "制品", "读取", "查看"),
        module_ids=("workspace",),
        tool_ids=("workspace.file.list", "workspace.file.read", "workspace.file.preview", "workspace.artifact.read"),
        prompt_hints=("Read workspace files before parsing domain content.",),
        output_kinds=("text",),
        priority=10,
    ),
    CapabilityPackage(
        capability_id="knowledge_qa",
        display_name="Knowledge QA",
        description="Search and read indexed knowledge.",
        intent_keywords=("knowledge", "docs", "文档", "知识", "资料", "手册", "查询"),
        module_ids=("knowledge",),
        tool_ids=("knowledge.search", "knowledge.chunk.read", "knowledge.source.read"),
        output_kinds=("summary",),
        priority=20,
    ),
    CapabilityPackage(
        capability_id="memory_lookup",
        display_name="Memory Lookup",
        description="Search or inspect memory and profile facts.",
        intent_keywords=("memory", "remember", "记忆", "偏好", "画像", "之前"),
        module_ids=("memory",),
        tool_ids=("memory.search", "memory.list", "memory.profile.get"),
        priority=30,
    ),
    CapabilityPackage(
        capability_id="config_translation",
        display_name="Config Translation",
        description="Parse, translate, compare and summarize network configuration text.",
        intent_keywords=("config", "configuration", "translate", "配置", "翻译", "转换", "厂商", "h3c", "cisco", "huawei"),
        module_ids=("config_translation", "config_analysis", "workspace"),
        tool_ids=("workspace.file.list", "workspace.file.read", "config.analysis.run"),
        prompt_hints=("Translated config is analysis output, not deployable configuration.",),
        output_kinds=("markdown", "translated_config"),
        safety_notes=("Do not claim translated configuration is production-ready."),
        priority=5,
    ),
    CapabilityPackage(
        capability_id="pcap_analysis",
        display_name="PCAP Analysis",
        description="Parse and inspect packet capture files.",
        intent_keywords=("pcap", "pcapng", "packet", "抓包", "报文", "五元组", "tcp", "重传"),
        module_ids=("pcap_analysis", "workspace"),
        tool_ids=("workspace.file.list", "pcap.analysis.run"),
        output_kinds=("summary", "table"),
        priority=6,
    ),
    CapabilityPackage(
        capability_id="report_drafting",
        display_name="Report Drafting",
        description="Render reports and save report artifacts.",
        intent_keywords=("report", "markdown", "总结", "报告", "整理", "导出"),
        module_ids=("report", "workspace"),
        tool_ids=("report.markdown.render", "report.artifact.save", "workspace.artifact.save"),
        output_kinds=("markdown", "artifact"),
        priority=40,
    ),
    CapabilityPackage(
        capability_id="runtime_diagnostics",
        display_name="Runtime Diagnostics",
        description="Inspect runtime health and diagnostics.",
        intent_keywords=("runtime", "diagnostic", "health", "运行", "诊断", "健康", "自检"),
        module_ids=("runtime",),
        tool_ids=("runtime.health", "runtime.diagnostics", "runtime.selfcheck"),
        priority=50,
    ),
)


CORE_TOOL_IDS: tuple[str, ...] = (
    "skill.search",
    "skill.load",
    "workspace.file.list",
    "workspace.file.read",
    "workspace.artifact.read",
    "tool.catalog.search",
)


def package_by_id(capability_id: str) -> CapabilityPackage | None:
    for package in CAPABILITY_PACKAGES:
        if package.capability_id == capability_id:
            return package
    return None
