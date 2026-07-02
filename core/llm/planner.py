"""
LLM Planner — Pure planning with snapshot isolation.

Invariants:
  - Input = snapshot(events) — immutable, frozen at call time
  - NO live stream access
  - NO runtime state awareness
  - Output = ExecutionPlan nodes only
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class PlannerSnapshot:
    """Immutable snapshot passed to LLM. No live event access."""
    user_input: str
    tools: tuple[tuple[str, str, dict], ...]  # (name, description, args)
    timestamp_iso: str

    def to_prompt_context(self) -> str:
        """Build tools description for prompt."""
        lines = []
        for name, desc, args in self.tools:
            arg_str = ", ".join(
                f"{k}: {v.get('type', 'string')}" for k, v in args.items()
            ) if args else "无参数"
            lines.append(f"- **{name}**: {desc} (参数: {arg_str})")
        return "\n".join(lines)


@dataclass(frozen=True)
class PlannerOutput:
    nodes: tuple[dict[str, Any], ...] = ()
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


# ── Planner ────────────────────────────────────────────────────────────

class Planner:
    """Pure planning. Snapshot input → Plan output."""

    def __init__(self, llm_invoke: Callable[..., str]):
        self._llm = llm_invoke

    def plan(self, snapshot: PlannerSnapshot) -> PlannerOutput:
        """Generate plan from immutable snapshot. No live state access.

        Args:
            snapshot: Frozen PlannerSnapshot — immutable at call time
        Returns:
            PlannerOutput with plan nodes
        """
        tools_desc = snapshot.to_prompt_context()
        system = PLANNER_SYSTEM_PROMPT.format(tools_description=tools_desc)

        raw = self._llm(
            system=system,
            user=snapshot.user_input,
            temperature=0.0,
        )
        return self._parse(raw)

    def _parse(self, raw_output: str) -> PlannerOutput:
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
            import re
            match = re.search(r'\{[\s\S]*\}', cleaned)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return PlannerOutput(final_response=raw_output.strip(), raw_llm_output=raw_output)
            else:
                return PlannerOutput(final_response=raw_output.strip(), raw_llm_output=raw_output)

        nodes = tuple(data.get("nodes", [])) if isinstance(data, dict) else ()
        fr = data.get("final_response", "") if isinstance(data, dict) else ""
        return PlannerOutput(nodes=nodes, final_response=fr, raw_llm_output=raw_output)

    def validate(self, output: PlannerOutput) -> list[str]:
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
                        errors.append(f"节点[{i}] (id='{nid}'): 依赖 '{dep}' 不存在")
        return errors

    def build_snapshot(self, user_input: str, tools: dict[str, dict]) -> PlannerSnapshot:
        """Build an immutable snapshot for planning. Frozen at this point."""
        from core.time.clock import _diff_ms as _unused
        import datetime
        tools_tuple = tuple(
            (name, meta.get("description", ""), meta.get("args", {}))
            for name, meta in tools.items()
        )
        return PlannerSnapshot(
            user_input=user_input,
            tools=tools_tuple,
            timestamp_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
