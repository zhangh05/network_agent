"""Lightweight conflict detection for durable memory writes."""

from __future__ import annotations

import re


NEGATIVE_MARKERS = ("不", "不要", "禁止", "禁用", "不允许", "不能", "无需", "关闭", "避免", "否")
POSITIVE_MARKERS = ("采用", "允许", "启用", "需要", "必须", "开启", "使用", "可以", "是")


def detect_memory_conflicts(
    *,
    title: str,
    content: str,
    memory_type: str,
    project_id: str = "",
    tags: list | None = None,
    limit: int = 5,
) -> list[dict]:
    """Return likely conflicts with existing memory records.

    This is deterministic and intentionally conservative: it only reports a
    conflict when an existing record is topically similar and polarity differs.
    """
    try:
        from memory.store import get_store
        existing = get_store().list(
            memory_type=memory_type or None,
            project_id=project_id or None,
            limit=500,
        )
    except Exception:
        return []
    incoming_text = f"{title} {content}"
    incoming_terms = _topic_terms(incoming_text, tags or [])
    incoming_polarity = _polarity(incoming_text)
    if incoming_polarity == 0 or not incoming_terms:
        return []
    conflicts = []
    for rec in existing:
        old_text = " ".join([
            str(rec.get("title", "")),
            str(rec.get("summary", "")),
            str(rec.get("content", "")),
        ])
        old_polarity = _polarity(old_text)
        if old_polarity == 0 or old_polarity == incoming_polarity:
            continue
        old_terms = _topic_terms(old_text, rec.get("tags") or [])
        overlap = incoming_terms & old_terms
        if not overlap:
            continue
        conflicts.append({
            "memory_id": rec.get("memory_id", ""),
            "title": rec.get("title", ""),
            "memory_type": rec.get("memory_type", ""),
            "scope": rec.get("scope", ""),
            "overlap_terms": sorted(overlap)[:8],
            "existing_polarity": "positive" if old_polarity > 0 else "negative",
            "incoming_polarity": "positive" if incoming_polarity > 0 else "negative",
            "summary": str(rec.get("summary", ""))[:180],
        })
        if len(conflicts) >= limit:
            break
    return conflicts


def _polarity(text: str) -> int:
    text = str(text or "")
    strong_negative = ("不采用", "不允许", "不能", "不要", "禁止", "禁用", "关闭", "避免")
    if any(marker in text for marker in strong_negative):
        return -1
    neg = sum(1 for marker in NEGATIVE_MARKERS if marker in text)
    pos = sum(1 for marker in POSITIVE_MARKERS if marker in text)
    if neg > pos:
        return -1
    if pos > neg:
        return 1
    return 0


def _topic_terms(text: str, tags: list) -> set[str]:
    raw = [str(t).lower() for t in tags or []]
    raw.extend(re.findall(r"[A-Za-z0-9_./-]+", str(text).lower()))
    raw.extend(re.findall(r"[\u4e00-\u9fff]{2,}", str(text)))
    stop = {"用户偏好", "本项目", "默认", "回答", "问题", "策略", "配置", "需要", "使用", "允许", "采用", "不采用", "不允许"}
    return {t for t in raw if len(t) >= 2 and t not in stop}
