# agent/runtime/tasking/detector.py
"""Detect whether user input implies a new task, continuation, or simple chat."""

from __future__ import annotations

import re
from typing import Optional

from agent.runtime.tasking.models import TaskSignal
from agent.runtime.state.models import RuntimeState

# Keywords that suggest a multi-step task
_NEW_TASK_VERBS = re.compile(
    r"(整理|生成|分析|对比|输出|制作|汇总|规划|改造|排查|重构|迁移|部署|构建|搭建|实现|开发|设计)"
)
_MULTI_STEP_INDICATORS = re.compile(
    r"(并且|然后|同时|接着|最后|首先|第一步|分步|依次|逐一|步骤|流程|方案|计划|多个|批量|全部|所有)"
)

# Continue-task keywords
_CONTINUE_KEYWORDS = re.compile(
    r"(继续|接着|下一步|按刚才|继续处理|接着做|继续执行|往下)"
)

# Cancel keywords
_CANCEL_KEYWORDS = re.compile(
    r"(取消|先停|不用做了|算了|停止|中止|别做了)"
)

# Simple chat patterns — these should NOT become tasks
_SIMPLE_PATTERNS = re.compile(
    r"^(你好|hi|hello|hey|谢谢|thank|翻译|translate|什么是|what is|解释|explain|帮我翻译)",
    re.IGNORECASE,
)


class TaskDetector:
    """Classify user input into a TaskSignal."""

    def detect(
        self,
        user_input: str,
        ctx=None,
        state: Optional[RuntimeState] = None,
    ) -> TaskSignal:
        text = user_input.strip()
        if not text:
            return TaskSignal(kind="none", confidence=0.9, reason="empty_input")

        # Cancel check
        if _CANCEL_KEYWORDS.search(text):
            if state and state.active_task:
                return TaskSignal(
                    kind="cancel_task",
                    confidence=0.85,
                    reason="cancel_keyword_detected",
                    referenced_task_id=state.active_task.task_id,
                )

        # Continue check — requires active task
        if _CONTINUE_KEYWORDS.search(text):
            if state and state.active_task:
                return TaskSignal(
                    kind="continue_task",
                    confidence=0.85,
                    reason="continue_keyword_with_active_task",
                    referenced_task_id=state.active_task.task_id,
                )

        # Simple chat / translate / single QA → none
        if _SIMPLE_PATTERNS.search(text):
            return TaskSignal(kind="none", confidence=0.9, reason="simple_chat_pattern")

        # Short single-sentence without task verbs → none
        if len(text) < 10 and not _NEW_TASK_VERBS.search(text):
            return TaskSignal(kind="none", confidence=0.8, reason="too_short_no_task_verb")

        # New task detection: task verb + multi-step indicator
        has_verb = bool(_NEW_TASK_VERBS.search(text))
        has_multi = bool(_MULTI_STEP_INDICATORS.search(text))

        if has_verb and has_multi:
            return TaskSignal(
                kind="new_task",
                confidence=0.9,
                reason="task_verb_and_multi_step_indicator",
            )

        if has_verb and len(text) > 30:
            return TaskSignal(
                kind="new_task",
                confidence=0.7,
                reason="task_verb_with_long_description",
            )

        return TaskSignal(kind="none", confidence=0.6, reason="no_task_signal")
