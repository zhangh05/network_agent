"""
LLM Planner — Pure planning layer.

Replaces:
  - speg_engine/planner.py  LLM planning + prompt
  - tool chain / dependency logic

Rules:
  - ONLY output: ExecutionPlan (list of node dicts)
  - NO tool execution
  - NO state mutation
  - NO timing logic
  - NO graph access

Key addition: $dep.<id>.data  syntax taught to LLM for tool chaining.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Output type ───────────────────────────────────────────────────────

@dataclass
class PlannerOutput:
    """What the planner returns. Single source of truth for plan data."""
    nodes: list[dict[str, Any]] = field(default_factory=list)
    final_response: str = ""
    raw_llm_output: str = ""


# ── System prompt ────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """你是一个任务执行规划器。根据用户的请求，生成一个工具调用计划。

## 输出格式
只输出一个 JSON 对象，不要包含其他文字：
```json
{{
  "nodes": [
    {{
      "id": "唯一的节点ID（英文）",
      "tool": "工具名称",
      "args": {{ "参数名": "参数值" }},
      "deps": ["依赖的节点ID列表"]
    }}
  ],
  "final_response": "如果没有工具需要调用，这是直接回复用户的内容"
}}
```

## 工具链式调用（重要！）
如果一个工具需要另一个工具的输出作为输入，使用 **$dep.<节点ID>.data** 引用：

例：先获取设备信息，再用IP做巡检
```json
{{
  "nodes": [
    {{
      "id": "get_device",
      "tool": "device.manage",
      "args": {{"action": "get", "name": "核心交换机"}},
      "deps": []
    }},
    {{
      "id": "inspect_device",
      "tool": "inspection.manage",
      "args": {{
        "action": "run",
        "target_ip": "$dep.get_device.data"
      }},
      "deps": ["get_device"]
    }}
  ]
}}
```

## 规则
1. 每个节点有唯一 id（英文）
2. tool 必须是可用的工具名
3. args 中的值可以是用 $dep.<节点ID>.data 引用上游结果
4. deps 列出此节点依赖的节点 id：若 B 需要 A 的输出，则 B.deps 包含 A.id
5. 没有依赖关系的节点会被并行执行
6. 不要对可以独立运行的工具进行链式调用
7. 如果用户请求不需要任何工具，nodes 设为空数组，在 final_response 中给出回复
8. 只输出 JSON，不要输出解释或备注

## 可用的工具列表
{tools_description}
"""


# ── Tool description builder ─────────────────────────────────────────

def build_tools_description(tools: dict[str, dict]) -> str:
    """Build a human-readable tool list for the planner prompt."""
    lines = []
    for name, meta in tools.items():
        desc = meta.get("description", name)
        args = meta.get("args", {})
        arg_str = ", ".join(
            f"{k}: {v.get('type', 'string')}" for k, v in args.items()
        ) if args else "无参数"
        lines.append(f"- **{name}**: {desc} (参数: {arg_str})")
    return "\n".join(lines)


# ── Planner ──────────────────────────────────────────────────────────

class Planner:
    """Pure planning. Takes user input → returns ExecutionPlan nodes."""

    def __init__(
        self,
        llm_invoke: Callable[..., str],
        tools: dict[str, dict] | None = None,
    ):
        self._llm = llm_invoke
        self._tools = tools or {}

    def register_tool(self, name: str, description: str = "",
                      args: dict | None = None) -> None:
        self._tools[name] = {
            "description": description,
            "args": args or {},
        }

    def plan(self, user_input: str) -> PlannerOutput:
        """Generate an execution plan from user input.

        Pure function: input → LLM → plan JSON. No side effects.
        """
        tools_desc = build_tools_description(self._tools)
        system = PLANNER_SYSTEM_PROMPT.format(tools_description=tools_desc)

        raw = self._llm(
            system=system,
            user=user_input,
            temperature=0.0,
        )

        return self._parse(raw)

    def _parse(self, raw_output: str) -> PlannerOutput:
        """Parse LLM output into PlannerOutput."""
        output = PlannerOutput(raw_llm_output=raw_output)

        # Strip markdown fences
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re
            match = re.search(r'\{[\s\S]*\}', cleaned)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    # Return raw output as final_response
                    output.final_response = raw_output.strip()
                    return output
            else:
                output.final_response = raw_output.strip()
                return output

        if isinstance(data, dict):
            nodes = data.get("nodes", [])
            if isinstance(nodes, list):
                output.nodes = nodes
            fr = data.get("final_response", "")
            if fr and isinstance(fr, str):
                output.final_response = fr

        return output

    def validate(self, output: PlannerOutput) -> list[str]:
        """Validate planner output. Returns list of errors (empty = valid)."""
        errors = []
        seen_ids = set()

        for i, node in enumerate(output.nodes):
            nid = node.get("id", "")
            tool = node.get("tool", "")

            if not nid or not isinstance(nid, str):
                errors.append(f"节点[{i}]: id 必须是非空字符串")
            elif nid in seen_ids:
                errors.append(f"节点[{i}]: id '{nid}' 重复")
            else:
                seen_ids.add(nid)

            if not tool or not isinstance(tool, str):
                errors.append(f"节点[{i}] (id='{nid}'): tool 必须是非空字符串")

            deps = node.get("deps", [])
            if not isinstance(deps, list):
                errors.append(f"节点[{i}] (id='{nid}'): deps 必须是数组")
            else:
                for dep in deps:
                    if dep not in seen_ids:
                        errors.append(
                            f"节点[{i}] (id='{nid}'): 依赖 '{dep}' 不存在或未定义"
                        )

        return errors
