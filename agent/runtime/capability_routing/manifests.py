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
        package="workspace.memory_governance",
        service_path="workspace.memory_governance",
        operations=("search", "list", "profile"),
    ),
    "browser": ModuleServiceManifest(
        module_id="browser",
        package="agent.modules.browser",
        service_path="agent.modules.browser.core",
        operations=("browser_navigate", "browser_extract", "browser_screenshot", "browser_close"),
        kind="business",
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
    "pcap": ModuleServiceManifest(
        module_id="pcap",
        package="agent.modules.pcap",
        service_path="agent.modules.pcap.service",
        operations=("parse", "session", "filter", "align"),
        kind="business",
    ),
    "artifact": ModuleServiceManifest(
        module_id="artifact",
        package="agent.modules.artifact",
        service_path="agent.modules.artifact.service",
        operations=("list", "read"),
    ),
    "review": ModuleServiceManifest(
        module_id="review",
        package="agent.modules.review",
        service_path="agent.modules.review.service",
        operations=("list", "update"),
    ),
    "coding": ModuleServiceManifest(
        module_id="coding",
        package="agent.modules.git",
        service_path="agent.modules.git.core",
        operations=("status", "diff", "log", "commit", "push", "search"),
    ),
    "remote": ModuleServiceManifest(
        module_id="remote",
        package="agent.modules.remote",
        service_path="agent.modules.remote.service",
        operations=("connect_device", "ssh_connect", "telnet_connect"),
        kind="business",
    ),
    "runtime": ModuleServiceManifest(
        module_id="runtime",
        package="agent.runtime",
        service_path="agent.runtime.services",
        operations=("health", "diagnostics", "trace"),
    ),
    "cmdb": ModuleServiceManifest(
        module_id="cmdb",
        package="agent.modules.cmdb",
        service_path="agent.modules.cmdb.service",
        operations=("list_assets", "get_asset", "add_asset", "delete_asset"),
    ),
}


CAPABILITY_PACKAGES: tuple[CapabilityPackage, ...] = (
    CapabilityPackage(
        capability_id="workspace_read",
        display_name="Workspace Read",
        description="Read or inspect workspace files and artifacts.",
        intent_keywords=("file", "workspace", "artifact", "文件", "制品", "读取", "查看"),
        module_ids=("workspace",),
        tool_ids=("workspace.file.list", "workspace.file.read", "workspace.artifact.read"),
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
        tool_ids=("knowledge.search", "knowledge.read"),
        output_kinds=("summary",),
        priority=20,
    ),
    CapabilityPackage(
        capability_id="memory_lookup",
        display_name="Memory Lookup",
        description="Search or inspect memory and profile facts.",
        intent_keywords=("memory", "remember", "记忆", "偏好", "画像", "之前"),
        module_ids=("memory",),
        tool_ids=("memory.search", "memory.profile"),
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
        module_ids=("pcap", "workspace"),
        tool_ids=("workspace.file.list", "pcap.analysis.run"),
        output_kinds=("summary", "table"),
        priority=6,
    ),
    CapabilityPackage(
        capability_id="report_drafting",
        display_name="Report Drafting",
        description="Render reports and save report artifacts.",
        intent_keywords=("report", "markdown", "总结", "报告", "整理", "导出"),
        module_ids=("workspace",),
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
        tool_ids=("system.diagnostics",),
        priority=50,
    ),
    CapabilityPackage(
        capability_id="cmdb",
        display_name="CMDB 设备资产",
        description="查询、添加、删除网络设备资产。每个资产记录名称、类型、厂商、型号、IP、连接方式。",
        intent_keywords=("cmdb", "设备", "资产", "添加设备", "录入设备", "新增设备",
                         "删除设备", "有哪些设备", "查设备", "看设备", "设备资产",
                         "资产管理", "设备清单", "设备列表", "设备名",
                         "多少设备", "几个设备", "添加", "新增", "录入", "asset"),
        module_ids=("cmdb",),
        tool_ids=("device.list", "device.get", "device.add", "device.delete"),
        output_kinds=("table", "summary"),
        safety_notes=("不可声明 CMDB 中存在未从工具返回的设备。", "添加/删除操作需确认。"),
        priority=7,
    ),
    CapabilityPackage(
        capability_id="network_device",
        display_name="Network 设备 SSH/Telnet",
        description="SSH / Telnet 连接网络设备并执行命令。先通过 CMDB 获取设备信息，再调用连接工具。",
        intent_keywords=("ssh", "telnet", "连接", "登录设备", "display", "show run",
                         "执行命令", "show version", "display version"),
        module_ids=("remote",),
        tool_ids=("exec.run",),
        output_kinds=("text",),
        safety_notes=("真实设备访问，需审批。", "危险命令（reload/erase/format）自动拦截。"),
        priority=6,
    ),
    CapabilityPackage(
        capability_id="browser",
        display_name="Browser 浏览器自动化",
        description="使用 Playwright 浏览器导航网页、提取内容、截图、点击交互。",
        intent_keywords=("browser", "浏览器", "网页", "打开链接", "截图", "提取内容",
                         "navigate", "screenshot", "scrape", "访问网站", "查看网页",
                         "打开网页", "页面内容", "抓取"),
        module_ids=("browser",),
        tool_ids=("browser.navigate", "browser.extract", "browser.screenshot", "browser.click"),
        prompt_hints=("Browser provides real-time web page content. Always prefer browser over web.page.process when interactive browsing is needed.",),
        output_kinds=("text", "image"),
        safety_notes=("浏览器内容来自外部网站，可能不准确。禁止访问内网/需登录页面。",),
        priority=8,
    ),
)


CORE_TOOL_IDS: tuple[str, ...] = (
    # ── Tool discovery ──
    "tool.catalog.search",
    # ── Workspace ──
    "workspace.file.list", "workspace.file.read",
    "workspace.artifact.read",
    # ── Exec — unified command execution ──
    "exec.run",
    # ── Browser automation ──
    "browser.navigate", "browser.extract",
    "browser.screenshot", "browser.click",
    # ── Web / info ──
    "web.search",
    "web.page.process",
    "web.weather",
    # ── Device assets ──
    "device.list", "device.get",
    "device.add", "device.delete",
    # ── Git ──
    "git.status", "git.diff", "git.log",
    # ── Code search ──
    "code.search",
)


def package_by_id(capability_id: str) -> CapabilityPackage | None:
    for package in CAPABILITY_PACKAGES:
        if package.capability_id == capability_id:
            return package
    return None
