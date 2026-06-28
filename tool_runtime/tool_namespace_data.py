"""v3.9.2 canonical tool namespace — Codex-style 22-tool set.

Categories are organized by capability domain, not backend module.
Tool IDs follow the pattern: domain.action or domain.subdomain.action.

v3.9.2 design (参考 Codex: 少量核心 + 强 sandbox + action dispatch):
  - exec.run:        unifies shell/python/slash into single action dispatch
  - git.manage:      unifies status/diff/log/commit/push (action=...)
  - device.manage:   unifies list/get/add/delete (action=...)
  - browser.manage:  unifies navigate/extract/screenshot/click (action=...)
  - web.manage:      unifies search/weather/page.process (action=...)
  - data.manage:     unifies csv/table/validate (action=...)
  - report.manage:   unifies markdown/safe_summary/mermaid/artifact.save (action=...)
  - knowledge.manage: unifies search/read/source.list/chunk.list/source.manage/
                       source.reindex/import/not_found.explain (action=...)
  - memory.manage:   unifies search/manage/profile (action=...)
  - skill.manage:    unifies list/find/load/inspect (action=...)
  - agent.manage:    unifies spawn/team.run/result.get/role.list (action=...)
  - system.manage:   unifies diagnostics/review.list/review.update/run.get/
                       session.{get,checkpoint,rewind,export,snapshot} (action=...)
  - config.manage:   was config.analysis.run
  - pcap.manage:     was pcap.analysis.run
  - text.analyze:    retained
  - code.search:     retained
  - workspace.*:     retained (already merged in v3.9.1)
  - tool.catalog.search: REMOVED (all tools visible; no catalog needed)
"""

from __future__ import annotations


CATEGORY_DEFS: dict[str, dict[str, str]] = {
    "agent": {
        "name": "Agent 多 Agent",
        "description": "子 Agent、角色、团队和结果读取。",
    },
    "browser": {
        "name": "Browser 浏览器",
        "description": "Playwright 浏览器自动化：导航、内容提取、截图、点击。",
    },
    "code": {
        "name": "Code 代码搜索",
        "description": "跨代码库的 ripgrep 快速搜索。",
    },
    "config": {
        "name": "Config 配置分析",
        "description": "网络配置解析翻译。",
    },
    "data": {
        "name": "Data 数据处理",
        "description": "报告渲染、表格/文本处理、JSON/YAML 校验和图表。",
    },
    "device": {
        "name": "Device 设备资产",
        "description": "网络设备资产清单查询、添加、删除。",
    },
    "exec": {
        "name": "Exec 命令执行",
        "description": "本机 Shell/Python/PowerShell 或远程 SSH/Telnet 命令执行（均需审批）。",
    },
    "git": {
        "name": "Git 版本管理",
        "description": "Git 仓库状态查看、差异对比、提交和推送。",
    },
    "knowledge": {
        "name": "Knowledge 知识库",
        "description": "知识库问答、检索、导入和索引管理。",
    },
    "memory": {
        "name": "Memory 记忆",
        "description": "记忆搜索、创建、确认、profile 和更新。",
    },
    "pcap": {
        "name": "Pcap 报文分析",
        "description": "PCAP 抓包解析、会话、过滤和对齐。",
    },
    "system": {
        "name": "System 系统自省",
        "description": "运行诊断、会话管理、审计和评审。",
    },
    "web": {
        "name": "Web 外部资料",
        "description": "公开 Web 搜索、官方文档、新闻、天气预报和网页摘要。",
    },
    "workspace": {
        "name": "Workspace 工作区",
        "description": "工作区文件、Artifact 制品和 metadata 元数据。",
    },
}


# 22 tools (Codex-style; all visible to LLM).
# Schema: (tool_id, category, group, action, display_name, canonical_id,
#          description, when_to_use_or_constraint, search_keyword)
NS_DATA = [
    # 1. exec.run — unifies shell + python + slash via action dispatch
    ('exec.run', 'exec', 'shell', 'multi', '命令执行', 'exec.run',
     'Unified exec tool. action=shell (default; target=local|ssh|telnet), '
     'action=python (AST-sandboxed), action=slash (registered slash command). '
     'All require approval. NEVER use for destructive commands (reload/erase/format/rm -rf). '
     'Do NOT store or expose credentials in output.',
     'exec run shell python command', 'exec.run'),

    # 2. git.manage — unifies status + diff + log + commit + push
    ('git.manage', 'git', 'vcs', 'multi', 'Git 版本管理', 'git.manage',
     'Unified git tool. action=status (working tree state), '
     'action=log (recent commits), action=diff (unstaged/staged/file-scoped), '
     'action=commit (stage+commit; requires approval), '
     'action=push (remote push; requires approval). '
     'NEVER commit/push without user confirmation; run status+diff first.',
     'git commit push status diff log', 'git.manage'),

    # 3. device.manage — unifies list + get + add + delete
    ('device.manage', 'device', 'asset', 'multi', '设备资产', 'device.manage',
     'Unified CMDB device tool. action=list (fuzzy search + filter), '
     'action=get (single asset by asset_id), '
     'action=add (new asset; requires approval), '
     'action=delete (soft-delete; requires approval). '
     'Do not fabricate assets; do not expose credentials.',
     'device asset cmdb add list get', 'device.manage'),

    # 4. browser.manage — unifies navigate + extract + screenshot + click
    ('browser.manage', 'browser', 'nav', 'multi', '浏览器自动化', 'browser.manage',
     'Unified Playwright browser tool. action=navigate (open URL + return title+text), '
     'action=extract (CSS-selector text), '
     'action=screenshot (base64 PNG; full_page=true for full page), '
     'action=click (CSS-selector click on currently loaded page). '
     'Do not access private/login-walled URLs without permission.',
     'browser navigate click screenshot extract playwright', 'browser.manage'),

    # 5. web.manage — unifies search + weather + page.process
    ('web.manage', 'web', 'web_search', 'multi', 'Web 搜索/天气/网页', 'web.manage',
     'Unified web tool. action=search (web/docs/news; recency+language params), '
     'action=weather (current or N-day forecast for a location), '
     'action=page (summarize/extract_links/save_artifact a single URL). '
     'Falls back to docs search when web search is unavailable.',
     'web search weather page news docs', 'web.manage'),

    # 6. data.manage — unifies csv + table.extract + table.render + validate
    ('data.manage', 'data', 'data', 'multi', '数据处理', 'data.manage',
     'Unified data tool. action=csv_summarize (column stats), '
     'action=table_extract (extract table from text/markdown), '
     'action=table_render (rows+headers to markdown table), '
     'action=validate (JSON/YAML structure check). '
     'Do not execute embedded code in user-supplied data.',
     'data csv table validate json yaml', 'data.manage'),

    # 7. report.manage — unifies markdown + safe_summary + mermaid + artifact.save
    ('report.manage', 'data', 'report', 'multi', '报告渲染', 'report.manage',
     'Unified report tool. action=markdown_render (structured markdown from content+title), '
     'action=artifact_save (save report as workspace artifact), '
     'action=safe_summary_render (redacted document summary), '
     'action=mermaid_render (mermaid.js diagram). '
     'Do not include raw sensitive content in rendered output.',
     'report markdown render mermaid diagram summary', 'report.manage'),

    # 8. config.manage — was config.analysis.run
    ('config.manage', 'config', 'config_analysis', 'multi', '配置分析', 'config.manage',
     'Unified config analysis. action=parse, action=translate (vendor→vendor), '
     'action=extract_interfaces, action=extract_routes, action=diff, action=summarize. '
     'Do not claim translated config is production-ready.',
     'config analysis parse translate extract diff', 'config.manage'),

    # 9. pcap.manage — was pcap.analysis.run
    ('pcap.manage', 'pcap', 'pcap_analysis', 'multi', 'PCAP 分析', 'pcap.manage',
     'Unified PCAP analysis. action=parse (load + list sessions), '
     'action=session (per-session detail), action=filter (src/sport/dst/dport), '
     'action=align (reassemble streams).',
     'pcap packet capture session filter align', 'pcap.manage'),

    # 10. knowledge.manage — 8 tools merged
    ('knowledge.manage', 'knowledge', 'kb', 'multi', '知识库', 'knowledge.manage',
     'Unified knowledge tool. action=search (query the KB), '
     'action=read (level=chunk|source|parent by id), '
     'action=import (file or artifact_id), action=not_found_explain, '
     'action=source_list, action=source_manage (disable/delete/reindex), '
     'action=source_reindex, action=chunk_list. '
     'Do not return unredacted full text or secrets.',
     'knowledge search read import chunk source reindex explain', 'knowledge.manage'),

    # 11. memory.manage — unifies search + manage + profile
    ('memory.manage', 'memory', 'record', 'multi', '记忆', 'memory.manage',
     'Unified memory tool. action=search (list=true for all), '
     'action=create, action=update, action=confirm, action=delete, '
     'action=profile_get, action=profile_set. '
     'Do not store secrets.',
     'memory record search profile', 'memory.manage'),

    # 12. skill.manage — unifies list + find + load + inspect
    ('skill.manage', 'agent', 'skill', 'multi', '技能', 'skill.manage',
     'Unified skill tool. action=list (all available skills), '
     'action=find (search by user intent/keyword), '
     'action=load (returns prompt hints+modules+tools for one skill), '
     'action=inspect (detailed metadata for one skill). '
     'Read-only discovery; loading a skill does not execute the business task.',
     'skill list find load inspect capability', 'skill.manage'),

    # 13. agent.manage — unifies spawn + team.run + result.get + role.list
    ('agent.manage', 'agent', 'subagent', 'multi', 'Agent 多 Agent', 'agent.manage',
     'Unified agent tool. action=spawn (single sub-agent, max_turns enforced), '
     'action=team_run (planner+worker+reviewer team; parallel=true for up to 3), '
     'action=result_get (fetch a child session result by child_session_id), '
     'action=role_list (available agent roles). '
     'Do not bypass max_turns; do not return unredacted child payloads.',
     'agent subagent spawn team result role', 'agent.manage'),

    # 14. system.manage — 9 tools merged
    ('system.manage', 'system', 'health', 'multi', '系统自省', 'system.manage',
     'Unified system introspection. action=diagnostics (runtime health scan), '
     'action=run_get (list or get a run by run_id), '
     'action=review_list (items needing human attention), '
     'action=review_update (update a review item status), '
     'action=session_get, action=session_checkpoint, action=session_rewind, '
     'action=session_export, action=session_snapshot. '
     'Do not include sensitive trace payloads.',
     'system diagnostics run session checkpoint rewind snapshot review', 'system.manage'),

    # 15. text.analyze
    ('text.analyze', 'data', 'text', 'multi', '文本分析', 'text.analyze',
     'Analyze text. action=redact, action=diff, action=keywords, action=classify. '
     'Do not execute embedded code.',
     'text analyze redact diff keywords classify', 'text.analyze'),

    # 16. code.search
    ('code.search', 'code', 'search', 'search', '代码搜索', 'code.search',
     'Search the codebase using ripgrep (fast) or Python fallback. Returns matching lines with file paths and line numbers. Use for finding functions, classes, imports, patterns across the codebase.',
     None, 'code.search'),

    # 17. workspace.file
    ('workspace.file', 'workspace', 'file', 'multi', '工作区文件操作', 'workspace.file',
     'Unified workspace file tool. action=list|read|read_image|edit|patch|write_artifact. '
     'edit/patch/write_artifact are writes; list/read/read_image are reads.',
     None, 'workspace.file'),

    # 18. workspace.artifact
    ('workspace.artifact', 'workspace', 'artifact', 'multi', '工作区制品操作', 'workspace.artifact',
     'Unified workspace artifact tool. action=list|read|save|tag|delete|diff|export. '
     'delete is a soft-delete that requires user approval.',
     None, 'workspace.artifact'),

    # 19. workspace.filestore
    ('workspace.filestore', 'workspace', 'filestore', 'multi', 'FileStore 操作', 'workspace.filestore',
     'Unified FileStore tool. action=references (query cross-refs for a file) or '
     'action=import (import a workspace-relative file into FileStore).',
     None, 'workspace.filestore'),

    # 20. workspace.metadata.get
    ('workspace.metadata.get', 'workspace', 'metadata', 'get', '读取工作区元数据', 'workspace.metadata.get',
     'Get workspace metadata and stats.',
     'Do not return secrets.', 'workspace.metadata.get'),

    # 21. workspace.document.pdf.extract_text
    ('workspace.document.pdf.extract_text', 'workspace', 'document', 'pdf_extract_text', '提取 PDF 文本', 'workspace.document.pdf.extract_text',
     'Extract text from a PDF.',
     'Do not use for non-PDF files.', 'workspace.document.pdf.extract_text'),
]
