"""Grounded, optional LLM explanations for deterministic assurance results."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.runtime import invoke_llm
from agent.llm.schemas import LLMMessage


def explain(purpose: str, evidence: list[dict[str, Any]], question: str) -> dict[str, Any]:
    """Ask the configured LLM to rank/explain facts without granting authority.

    Returned citations are restricted to evidence references supplied by the
    deterministic engine.  Failure or disabled LLM never blocks the workflow.
    """
    compact = [{
        "key": item.get("key"), "asset_name": item.get("asset_name") or "未知设备",
        "before": item.get("before"), "after": item.get("after"),
        "severity": item.get("severity"), "rationale": item.get("rationale"),
        "evidence_ref": item.get("evidence_ref"),
    } for item in evidence[:80]]
    allowed_refs = {str(item.get("evidence_ref", "")) for item in compact if item.get("evidence_ref")}
    messages = [
        LLMMessage(role="system", content=(
            "你是网络保障分析助手。只能依据给定的结构化事实，不得创造设备、链路、指标或结论。"
            "面向用户只能使用 asset_name 设备名称，不得输出或猜测内部 asset_id。"
            "输出 JSON：{summary:string, ranked_hypotheses:[{statement,confidence,evidence_refs}], next_actions:[string]}。"
            "confidence 只能是 likely 或 unverified；事实权威、阈值和最终通过状态由规则引擎决定。"
        )),
        LLMMessage(role="user", content=json.dumps({"purpose": purpose, "question": question, "evidence": compact}, ensure_ascii=False)),
    ]
    response = invoke_llm(task="assurance_grounded_analysis", messages=messages,
                          extra={"stream_to_user": False, "stream_scope": "internal"})
    if response.error or not response.content:
        return {"status": "unavailable", "error": str(response.error or "empty_response")[:200]}
    raw = response.content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S | re.I)
    if fenced:
        raw = fenced.group(1)
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"status": "invalid", "error": "llm_response_not_json"}
    if not isinstance(payload, dict):
        return {"status": "invalid", "error": "llm_response_not_object"}
    hypotheses = []
    for item in payload.get("ranked_hypotheses", []) if isinstance(payload.get("ranked_hypotheses"), list) else []:
        if not isinstance(item, dict):
            continue
        refs = [str(ref) for ref in item.get("evidence_refs", []) if str(ref) in allowed_refs]
        hypotheses.append({
            "statement": str(item.get("statement", ""))[:1000],
            "confidence": str(item.get("confidence", "unverified")) if item.get("confidence") in {"likely", "unverified"} else "unverified",
            "evidence_refs": refs,
        })
    return {
        "status": "completed", "summary": str(payload.get("summary", ""))[:3000],
        "ranked_hypotheses": hypotheses[:10],
        "next_actions": [str(item)[:500] for item in payload.get("next_actions", [])[:10]]
        if isinstance(payload.get("next_actions"), list) else [],
    }
