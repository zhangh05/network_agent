# agent/llm/tool_adapter.py
"""Tool adapter — convert ToolSpec to OpenAI function-calling format.

Tool name mapping for LLM function calling:
- LLM function names cannot contain dots (`.`)
- Convert `.` → `__` for LLM-safe names
- Convert `__` → `.` when mapping back to real tool_id

v3.0: the LLM-facing surface is canonical-only. The function name
and the description prefix both reference the canonical tool_id;
internal dispatch fields are never exposed to the model.
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
    """Convert a single ToolSpec dict to OpenAI function definition.

    v3.0 canonical-only: the description prefix carries only the
    canonical tool_id. Internal dispatch fields are stripped before
    this runs.
    """
    metadata = tool.get("metadata") or {}
    canonical_tool_id = (
        tool.get("canonical_tool_id")
        or metadata.get("canonical_tool_id")
        or tool.get("tool_id", "")
    )
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
            param["description"] = str(prop.get("description", ""))[:200]
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
    llm_name = to_llm_tool_name(canonical_tool_id)
    description = (tool.get("description") or tool.get("name") or canonical_tool_id)[:420]
    description = f"[tool_id={canonical_tool_id}] {description}"[:512]

    return {
        "type": "function",
        "function": {
            "name": llm_name,
            "description": description,
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
    from agent.runtime.services import default_runtime_services
    services = default_runtime_services()
    raw = []
    for spec in services.tool_service.registry.list_model_visible():
        raw.append({
            "tool_id": spec.tool_id,
            "name": spec.name,
            "description": spec.description,
            "risk_level": spec.risk_level,
            "enabled": spec.enabled,
            "input_schema": spec.input_schema,
            "metadata": getattr(spec, "metadata", {}) or {},
            **(getattr(spec, "metadata", {}) or {}),
        })
    return build_tool_registry_for_llm(raw)


def build_system_prompt_with_tools(workspace_id: str = "default") -> str:
    """Build the system prompt that tells the LLM about available tools.

    Uses LLM-safe tool names (with __ instead of .).
    v3.0: lists canonical tools only; the planner emits the
    capability_action plan; there is no alias / merge / replace
    layer in the dispatch path.
    """
    tools = list_tools_for_orchestrator()

    prompt = f"""You are Network Agent, a network-engineering AI assistant. You have {len(tools)} canonical tools available via function calling.

## v3.0 Scene-Based Tool Selection by Capability Action

Route every user request through: Category → Group → capability_action → canonical tool id.
Function names use canonical ids with dots converted to double underscores.
For multi-step requests, follow RuntimeContext tool_scene.tool_chain in order.
If RuntimeContext includes tool_scene.capability_plan/tool_plan, follow it as the execution plan.
Execute required steps first and respect stop_if_failed.
If needs_clarification=true, ask the clarifying_question before using tools.
Do not skip file reading before parsing uploaded files.
Do not use host.* tools for network device configuration parsing.

### host 本机环境
Use for local OS, localhost, IP, port, process, shell, PowerShell, and Python questions.
Examples: host__shell__exec, host__powershell__exec, host__python__exec.
Host tools run on the local machine only. They are NOT network device SSH/Telnet/SNMP.

### workspace 工作区 / Uploaded File
Use for workspace files, previews, metadata, and artifacts.
Examples: workspace__file__read, workspace__file__preview, workspace__artifact__search.

### network 网络分析
Use for offline network configuration, interface, route, translation, and packet capture analysis.
Examples: network__config__parse, network__interface__extract, network__route__extract,
network__config__translate, network__pcap__parse, network__pcap__align.
This is offline text analysis only; do not claim remote device access.

### web 外部资料
Use for public web, official docs, latest info, news, weather, and page summaries.
Examples: web__search, web__docs__official_search, web__page__summarize.

### knowledge 知识库
Use for local knowledge base search, sources, chunks, imports, and reindexing.
Examples: knowledge__query, knowledge__search, knowledge__chunk__read.

### memory 记忆
Use for remembered preferences, profile, confirmation, and memory updates.
Examples: memory__search, memory__profile__get, memory__profile__set.

### runtime 运行审计
Use for runtime health, sessions, runs, traces, checkpoints, and review items.
Examples: runtime__health, run__list, session__summary__get.

### report_data 输出处理
Use for reports, tables, diagrams, text transforms, JSON/YAML/CSV validation.
Examples: report__markdown__render, data__table__render, text__redact.

### agent 多 Agent
Use for skill loading, agent spawn/team/result, and role lookup.
Examples: agent__spawn, agent__role__list, agent__team__run.

## Tool Usage Rules

1. **Prefer specific tools over vague responses.** If a tool can answer the query, call it.
2. **One approval request per high-risk action.** Do not repeat the same approval request.
3. **Match tool to scenario.** host__shell__exec is for local host, NOT remote devices.
4. **When a tool fails, suggest the next tool.** Never leave the user with just an error.
5. **For high-risk tools: just call them.** The system will pop up an approval bubble
   for the user to allow/deny. You do NOT need to ask the user to type anything.
6. **Do NOT ask "which OS"** before selecting host__shell__exec vs host__powershell__exec.
   The tool descriptions guide OS selection; you can use this context.

## Approval Behavior (v3.0 — Popup Bubble)

- High-risk tools (host.shell.exec, host.powershell.exec, host.python.exec, etc.)
  require user approval, BUT the system handles this automatically with a popup bubble.
- You should call the tool directly. Briefly explain what you're about to do (1 sentence).
  Example: "我将查询本机 IP 地址。" then call host.shell.exec.
- Do NOT say "请回复批准执行", "请回复批准删除", or any approval request text.
- The user clicks Allow/Deny in the bubble; you do not need to manage this flow.

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
