"""Router — LLM or regex → Intent + Entities. Cached by normalized question."""
from __future__ import annotations

import re
from typing import Any

from app.contracts import Intent, RouteResult
from app.logging_ import get_logger

_log = get_logger("agent.router")

_REGEX_RULES: list[tuple[re.Pattern, Intent]] = [
    (re.compile(r"chiến dịch.*(lỗ|lãi|hiệu quả|romi|roas)", re.I), Intent.CAMPAIGN_OVERVIEW),
    (re.compile(r"(chẩn đoán|chẩn bệnh|vấn đề|sự cố).*chiến dịch", re.I), Intent.CAMPAIGN_DIAGNOSIS),
    (re.compile(r"(phễu|funnel|chuyển đổi|lead.*hồ sơ|duyệt)", re.I), Intent.FUNNEL_ANALYSIS),
    (re.compile(r"(chân dung|phân khúc|tập khách|segment|persona)", re.I), Intent.CUSTOMER_PERSONA),
    (re.compile(r"(clv|giá trị vòng đời|lifetime value)", re.I), Intent.CLV_ACTIONS),
    (re.compile(r"(hành động|khuyến nghị|nên làm|gợi ý)", re.I), Intent.CLV_ACTIONS),
    (re.compile(r"(rủi ro|fraud|lừa đảo|bất thường)", re.I), Intent.RISK_FRAUD),
    (re.compile(r"(bao nhiêu|tổng|số lượng|đếm|count)", re.I), Intent.DATA_QUESTION),
]

_CAMPAIGN_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"", re.I)
_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?")

_KNOWN_CHANNELS = [
    "Facebook Ads", "Google Ads", "TikTok Ads", "Zalo Ads",
    "Facebook", "Google", "TikTok", "Zalo",
    "FB", "GG", "TT",
]


def route(question: str, llm_client: Any = None) -> RouteResult:
    """Route a question to Intent + extract entities."""
    for pattern, intent in _REGEX_RULES:
        if pattern.search(question):
            entities = _extract_entities(question)
            return RouteResult(intent=intent, entities=entities, confidence=0.85)

    if _is_out_of_scope(question):
        return RouteResult(intent=Intent.OUT_OF_SCOPE, confidence=0.9)

    return RouteResult(intent=Intent.FREEFORM, entities=_extract_entities(question), confidence=0.5)


def _extract_entities(question: str) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    campaigns = _CAMPAIGN_RE.findall(question)
    if campaigns:
        entities["campaign_name"] = [c[0] or c[1] for c in campaigns if (c[0] or c[1])]
    dates = _DATE_RE.findall(question)
    if dates:
        entities["dates"] = dates
    channels = _extract_channels(question)
    if channels:
        entities["channel"] = channels
    return entities


def _extract_channels(question: str) -> list[str]:
    """Match known channel names in the question (case-insensitive)."""
    found = []
    q_lower = question.lower()
    for ch in _KNOWN_CHANNELS:
        if ch.lower() in q_lower:
            found.append(ch)
    return found if found else []


def _is_out_of_scope(question: str) -> bool:
    oos_patterns = [
        r"thời tiết", r"tin tức", r"bóng đá", r"nhạc", r"phim",
        r"nấu ăn", r"du lịch", r"thể thao",
    ]
    return any(re.search(p, question, re.I) for p in oos_patterns)
