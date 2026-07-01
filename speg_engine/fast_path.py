"""Fast-path classifier — narrow-rule direct-answer routing.

Purpose: skip the full SPEG planner/compiler/execution pipeline for
queries that clearly do not need tools (greetings, definition questions,
translation, summarisation).  The classifier is intentionally *narrow*:
only patterns that are unambiguous get the fast path; everything else
falls through to full SPEG.

Design principle: when in doubt, fall through — a false positive
(blocking a real tool need) is worse than a false negative (sending
a simple question to the planner).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FastPathDecision:
    enabled: bool
    route: str          # "greeting" | "simple_question" | "direct_answer" | ""
    reason: str


# ── Whitelist: patterns that enable fast path ──────────────────────

_GREETING_PATTERNS = (
    "你好", "hello", "hi ", "在吗", "你是谁", "你是",
    "hello!", "hi!",
)

_SIMPLE_QUESTION_PATTERNS = (
    "翻译", "润色", "改写", "总结这段", "总结一下", "概括",
    "解释一下", "是什么", "什么是", "什么叫", "的定义",
    "介绍一下", "了解", "区别",
)


# ── Blacklist: keywords that force full SPEG ──────────────────────

_BLACKLIST_KEYWORDS = (
    # Infrastructure
    "ping", "telnet", "traceroute", "访问慢",
    "排查", "检查", "查看", "读取", "文件",
    "执行", "命令", "接口", "交换机", "防火墙",
    "路由", "策略", "NAT", "VLAN", "OSPF 邻居",
    "BGP", "ISIS", "SRv6", "MTU", "光模块",
    "配置", "删除", "修改", "提交", "推送",
    # Network tools
    "ssh", "snmp", "netconf",
    # File system
    "README", "readme", ".md", ".py", ".yaml", ".json",
    "workspace/", "目录",
)


def _has_blacklist(text: str) -> bool:
    """Returns True if any blacklist keyword appears in *text*."""
    lower = text.lower()
    for kw in _BLACKLIST_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def classify_direct_answer(user_input: str) -> FastPathDecision:
    """Narrow-rule classifier: should this input skip the planner?

    Returns:
        FastPathDecision with ``enabled=True`` only for clear-cut
        non-tool scenarios (greetings, definition questions, etc.).

    Priority (highest to lowest):
      1. Greetings (short, unambiguous)
      2. Simple-question whitelist (是什么, 解释一下, 翻译, etc.)
      3. Blacklist (network / file system keywords) — only applied
         when whitelist patterns did NOT match
      4. Fall-through → full SPEG
    """
    text = (user_input or "").strip()
    if not text:
        return FastPathDecision(enabled=False, route="", reason="empty input")

    # 1.  Greeting patterns (very short, no ambiguity).
    for pat in _GREETING_PATTERNS:
        if text.lower().startswith(pat.lower()) and len(text) <= 10:
            return FastPathDecision(
                enabled=True, route="greeting",
                reason=f"greeting pattern: {pat}",
            )

    # 2.  Simple question / text-task patterns.  These take
    #     priority over the blacklist because a user asking
    #     "NAT 是什么" clearly does not want us to ssh into a
    #     firewall — they want a definition.
    for pat in _SIMPLE_QUESTION_PATTERNS:
        if pat in text:
            return FastPathDecision(
                enabled=True, route="simple_question",
                reason=f"simple question pattern: {pat}",
            )

    # 3.  Blacklist check — only applied when no whitelist pattern
    #     matched.  "OSPF 邻居起不来" has no whitelist pattern,
    #     so "OSPF 邻居" blocks it.  "NAT 是什么" matched "是什么"
    #     in step 2, so it fast-paths.
    if _has_blacklist(text):
        return FastPathDecision(enabled=False, route="", reason="blacklist_match")

    # 4.  Fall through — let full SPEG handle it.
    return FastPathDecision(
        enabled=False, route="",
        reason="no fast-path pattern matched",
    )
