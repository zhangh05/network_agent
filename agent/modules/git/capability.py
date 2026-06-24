# agent/modules/git/capability.py
"""Capability manifest for Coding — Git + Code Search."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_CODING = CapabilityManifest(
    capability_id="coding",
    name="Coding",
    status="enabled",
    description="版本管理与代码搜索：Git 操作（状态/差异/提交/推送）和跨代码库搜索（ripgrep）。",
    intent_patterns=[
        "git status", "git diff", "git log", "git commit", "git push",
        "commit", "push", "提交", "推送", "版本", "branch", "分支",
        "search code", "代码搜索", "find in code", "grep",
        "ripgrep", "rg", "查找代码", "搜索代码",
    ],
    prompt_summary=(
        "Coding 通用编码能力。Git 操作：status difflog commit push（提交/推送需用户审批）。"
        "Code Search：跨项目 ripgrep 搜索，支持正则和文件类型过滤。"
    ),
    module=CapabilityModuleSpec(
        module_id="coding",
        status="enabled",
        service_path="agent.modules.git.core",
        operations=["git_status", "git_diff", "git_log", "git_commit", "git_push", "search_code"],
        description="Git 版本管理与代码搜索。",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="git.status",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_git_status",
            description="查看 Git 仓库状态：修改、暂存、未跟踪文件和当前分支。",
        ),
        CapabilityToolRef(
            tool_id="git.diff",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_git_diff",
            description="查看 Git 差异（未暂存或已暂存），可选指定文件范围。",
        ),
        CapabilityToolRef(
            tool_id="git.log",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_git_log",
            description="查看 Git 提交历史，单行摘要格式。",
        ),
        CapabilityToolRef(
            tool_id="git.commit",
            status="enabled", callable_by_llm=True,
            risk_level="medium", requires_approval=True, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_git_commit",
            description="暂存并提交变更。需用户审批。先运行 git.status + git.diff。",
        ),
        CapabilityToolRef(
            tool_id="git.push",
            status="enabled", callable_by_llm=True,
            risk_level="medium", requires_approval=True, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_git_push",
            description="推送提交到远程仓库。需用户审批。",
        ),
        CapabilityToolRef(
            tool_id="code.search",
            status="enabled", callable_by_llm=True,
            risk_level="low", requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_code_search",
            description="跨代码库搜索（ripgrep 或 Python 回退）。返回匹配行、文件路径和行号。",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="git_result",
            output_type="git_result",
            description="Git 操作结果：状态输出、差异内容或提交确认。",
            artifact_type="text",
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
        notes="commit 和 push 操作需用户审批后才执行。status/diff/log/code.search 为只读。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0"},
)
