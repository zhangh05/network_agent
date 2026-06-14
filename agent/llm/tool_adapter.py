# agent/llm/tool_adapter.py
"""Tool adapter — convert ToolSpec to OpenAI function-calling format.

Tool name mapping for LLM function calling:
- LLM function names cannot contain dots (`.`)
- Convert `.` → `__` for LLM-safe names
- Convert `__` → `.` when mapping back to real tool_id

v2.1.2: Added comprehensive scene-based tool routing guidance.
"""

from typing import List


def to_llm_tool_name(tool_id: str) -> str:
    """Convert tool_id to LLM-safe function name.

    Examples:
        "runtime.health" -> "runtime__health"
        "web.search" -> "web__search"
        "artifact_list" -> "artifact_list"  (no dots, no change)
    """
    return tool_id.replace(".", "__")


def from_llm_tool_name(llm_name: str) -> str:
    """Convert LLM-safe function name back to real tool_id.

    Examples:
        "runtime__health" -> "runtime.health"
        "web__search" -> "web.search"
        "artifact_list" -> "artifact_list"  (no double underscore, no change)
    """
    return llm_name.replace("__", ".")


def tool_spec_to_openai_function(tool: dict) -> dict:
    """Convert a single ToolSpec dict to OpenAI function definition."""
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    params_def = {
        "type": "object",
        "properties": {},
        "required": required,
    }

    for name, prop in properties.items():
        param = {"type": prop.get("type", "string")}
        if prop.get("description"):
            param["description"] = str(prop["description"])[:200]
        if "enum" in prop:
            param["enum"] = prop["enum"]
        if "default" in prop:
            param["default"] = prop["default"]
        params_def["properties"][name] = param

    if not params_def["properties"]:
        params_def.pop("properties")
    if not params_def.get("required"):
        params_def.pop("required")

    # Use LLM-safe name (dots -> double underscore)
    llm_name = to_llm_tool_name(tool["tool_id"])

    return {
        "type": "function",
        "function": {
            "name": llm_name,
            "description": (tool.get("description") or tool.get("name") or tool["tool_id"])[:512],
            "parameters": params_def,
        },
    }


def build_tool_registry_for_llm(tools: List[dict]) -> List[dict]:
    """Build OpenAI-format tool definitions from ToolSpec dicts.

    Excludes forbidden tools and optionally disabled tools.
    Returns a list ready to pass as LLMRequest.tools.
    """
    result = []
    for tool in tools:
        if tool.get("risk_level") == "forbidden":
            continue
        if not tool.get("enabled", True):
            continue
        result.append(tool_spec_to_openai_function(tool))
    return result


def list_tools_for_orchestrator() -> List[dict]:
    """Get all enabled, non-forbidden tools as OpenAI function definitions.

    Returns the full list suitable for the LLM orchestrator's system context.
    """
    from tool_runtime.integration import get_default_tool_runtime_client
    client = get_default_tool_runtime_client()
    raw = client.list_tools()
    return build_tool_registry_for_llm(raw)


def build_system_prompt_with_tools(workspace_id: str = "default") -> str:
    """Build the system prompt that tells the LLM about available tools.

    Uses LLM-safe tool names (with __ instead of .).
    v2.1.2: Includes scene-based routing and tool selection guidance.
    """
    tools = list_tools_for_orchestrator()

    prompt = f"""You are Network Agent, a network-engineering AI assistant. You have {len(tools)} tools available via function calling.

## v2.1.2 Tool Selection by Scene

Match the user's intent to the correct tool category BEFORE calling:

### A. Local Host / OS Introspection (本机/当前机器/localhost/IP/端口/进程)
Use: runtime__health, runtime__diagnostics, shell__exec, powershell__exec.
These run commands ON THE LOCAL HOST — not on remote devices.
If the user asks for local IP, OS info, listening ports, or running processes,
call the tool directly. Do NOT say "no real device access".

### B. Uploaded Files / Configs / Logs / PCAP
Use: file__read, file__list, parser__extract_interfaces, parser__parse_config_text,
artifact__search, pdf__extract_text.
The material is already provided — analyze it. Do NOT claim device access is needed.

### C. Network Device Config Analysis (交换机/路由器/防火墙配置)
Use: parser__extract_interfaces, parser__extract_routes, text__classify,
text__extract_keywords, knowledge__search.
Without SSH/Telnet/SNMP, you cannot log into devices — but you CAN analyze
provided configurations. State this clearly.

### D. Web Search / Official Docs (查官方文档/厂商手册/最新信息)
Use: web__official_doc_search for vendor docs (Cisco/Huawei/H3C/Arista).
Use: web__search for general web queries.
Use: web__fetch_summary to read a specific URL.
Cite sources (URL, domain, date). Distinguish official vs community sources.

### E. Knowledge Base / Memory (知识库/记忆/之前说过/项目资料)
Use: knowledge__search, memory__search, artifact__search.
If not found, explain why and suggest alternatives (upload, web search).

### F. Report / Artifact Generation (生成报告/保存结果/导出)
Use: report__render_markdown, artifact__save_result, table__render_markdown,
diagram__render_mermaid, report__save_artifact.

### G. Session / Run History (之前那次/运行详情/trace)
Use: run__list_recent, run__get_summary, session__list, session__get_summary,
runtime__diagnostics.

### H. Memory Operations (记住/偏好/以后都这样)
Use: memory__create, memory__confirm, memory__set_profile.
Do NOT store secrets, tokens, or passwords.

## Tool Usage Rules

1. **Prefer specific tools over vague responses.** If a tool can answer the query, call it.
2. **One approval request per high-risk action.** Do not repeat the same approval request.
3. **Match tool to scenario.** shell__exec is for local host, NOT remote devices.
4. **When a tool fails, suggest the next tool.** Never leave the user with just an error.
5. **For read-only local commands:** generate approval once with the exact command.
6. **Do NOT ask "which OS"** before selecting shell__exec vs powershell__exec.
   The tool descriptions guide OS selection; you can use this context.

## Approval Phrasing (v2.1.2 Standard)

For high-risk read-only commands:
"可以执行。该命令只读不修改系统，按策略需要批准。将执行 `命令`。请回复'批准执行'。"

For write operations:
"可以使用工具写入 workspace artifact。影响范围仅限当前 workspace，不会访问真实网络设备。请回复'批准执行'。"

## Output Format for Network Engineering

For analysis questions, structure your answer as:
1. 结论 (Conclusion)
2. 证据 (Evidence from tools/citations)
3. 原因 (Root cause analysis)
4. 下一步验证 (Next step to verify)
5. 风险/注意事项 (Risks and caveats)

## Style
- Answer in Chinese for Chinese-speaking users.
- Be concise. Don't repeat tool names in your answer.
- If a tool returns useful data, summarize it clearly. If it fails, suggest alternatives.
- NEVER claim to execute commands on remote devices. NEVER output secrets.

Workspace: {workspace_id}"""

    return prompt
