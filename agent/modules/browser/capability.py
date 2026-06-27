# agent/modules/browser/capability.py
"""Capability manifest for Browser — Playwright web automation."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_BROWSER = CapabilityManifest(
    capability_id="browser",
    name="Browser",
    status="enabled",
    description="浏览器自动化：通过 Playwright 导航网页、提取内容、截图。用于阅读文档、检测网站状态。",
    intent_patterns=[
        "浏览器", "网页", "打开链接", "截图", "提取内容",
        "browser", "navigate", "screenshot", "scrape",
        "查看网页", "打开网页", "访问网站", "页面内容",
    ],
    prompt_summary=(
        "Browser 浏览器自动化（Playwright）。打开网页并返回标题和可见文本，"
        "支持 CSS 选择器内容提取。用于阅读在线文档或检测网站可用性。"
    ),
    module=CapabilityModuleSpec(
        module_id="browser",
        status="enabled",
        service_path="agent.modules.browser.core",
        operations=["browser_navigate", "browser_extract", "browser_screenshot", "browser_close"],
        description="Playwright 浏览器自动化。",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="browser.navigate",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_browser_navigate",
            description="打开浏览器并导航到 URL。返回页面标题和可见文本。",
        ),
        CapabilityToolRef(
            tool_id="browser.extract",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_browser_extract",
            description="通过 CSS 选择器提取网页元素的文本内容。",
        ),
        CapabilityToolRef(
            tool_id="browser.screenshot",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_browser_screenshot",
            description="对网页进行全页或视口截图，返回 base64 图片。",
        ),
        CapabilityToolRef(
            tool_id="browser.click",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_browser_click",
            description="点击当前页面上的元素（CSS 选择器）。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="browser_content",
            output_type="browser_content",
            description="网页内容或截图的结构化输出。",
            artifact_type="text",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=True,
        requires_human_review=False,
        notes="浏览器内容来自外部网站，可能不准确或过时。禁止访问内网/需登录的页面。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0"},
)
