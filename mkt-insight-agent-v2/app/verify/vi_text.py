"""Vietnamese proper noun extraction for L3 entity grounding.

1. Identifier codes: CMP-*, CUS-*, PRD-*, APP-*, LEAD-*
2. Sequences of >= 2 consecutive capitalized words
3. Fuzzy match via difflib (threshold 0.92)
"""
from __future__ import annotations

import re

_ID_PATTERNS = [
    re.compile(r"\b(CMP-\d+)\b"),
    re.compile(r"\b(CUS-\d+)\b"),
    re.compile(r"\b(PRD-\d+)\b"),
    re.compile(r"\b(APP-\d+)\b"),
    re.compile(r"\b(LEAD-\d+)\b"),
]

_VI_UPPER = (
    "A-Z"
    "ÀÁÂẦẨẪẬĐÈÉÊỀỂỄỆÌÍÒÓÔỒỔỖỘƠỜỞỠỢÙÚŨỤƯỪỬỮỰỲÝỸỶỴ"
)

_CAP_WORD = re.compile(rf"[{_VI_UPPER}][a-zà-ỹ]+")
_CAP_SEQ = re.compile(rf"(?:[{_VI_UPPER}][a-zà-ỹ]+\s+){{1,}}[{_VI_UPPER}][a-zà-ỹ]+")


def extract_proper_nouns_vi(text: str) -> list[str]:
    """Extract Vietnamese proper nouns from text."""
    found: list[str] = []
    for pat in _ID_PATTERNS:
        found.extend(pat.findall(text))
    for m in _CAP_SEQ.finditer(text):
        phrase = m.group(0).strip()
        words = phrase.split()
        if len(words) >= 2:
            found.append(phrase)
    seen: set[str] = set()
    result: list[str] = []
    for w in found:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def split_sentences_vi(text: str) -> list[str]:
    """Split Vietnamese text into sentences."""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def has_marker(sentence: str, markers: list[str]) -> bool:
    low = sentence.lower()
    for m in markers:
        if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", low):
            return True
    return False


def has_comparative_marker(sentence: str) -> bool:
    from app.verify.config import markers
    return has_marker(sentence, markers().get("comparative", []))


def has_causal_marker(sentence: str) -> bool:
    from app.verify.config import markers
    return has_marker(sentence, markers().get("causal", []))


def has_correlation_phrase(sentence: str) -> bool:
    correlation_phrases = [
        "tương quan", "liên quan", "đồng biến", "cùng chiều",
        "khi ... thì", "càng ... càng", "phù hợp với",
        "phân phối", "lệch", "trung bình", "trung vị", "độ lệch chuẩn",
        "phân vị", "khoảng tin cậy", "cỡ mẫu", "mẫu",
    ]
    low = sentence.lower()
    return any(p in low for p in correlation_phrases)
