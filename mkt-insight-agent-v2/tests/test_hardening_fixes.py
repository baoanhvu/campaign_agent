"""Tests for hardening fixes — severity, disambiguation, VI number format, entity regex."""
import pytest
from app.contracts import EvidenceSet, Fact, Severity
from app.verify.judge import _parse_judge_response, JudgeResult
from app.verify.stats_guard import check_stats_guard
from app.verify.vi_text import extract_proper_nouns_vi
from app.agent.streaming import _auto_tag_numbers
from app.verify.numeric import parse_vi_number


# ── Fix 1: L5 judge severity ──────────────────────────────────────────

def test_judge_contradiction_is_block():
    result = _parse_judge_response('{"label": "CONTRADICTED"}')
    assert result.contradiction_rate == 1.0


def test_judge_supported_is_not_contradiction():
    result = _parse_judge_response('{"label": "SUPPORTED"}')
    assert result.contradiction_rate == 0.0
    assert result.entailment_rate == 1.0


# ── Fix 3: Entity regex with Vietnamese uppercase ─────────────────────

def test_entity_regex_ascii_proper_noun():
    found = extract_proper_nouns_vi("Chiến dịch Zalo Ads cho kết quả tốt")
    assert any("Zalo" in f for f in found)


def test_entity_regex_vi_uppercase_diacritic():
    found = extract_proper_nouns_vi("Chiến dịch Ẩn Mật cho kết quả tốt")
    assert any("Ẩn" in f for f in found)


def test_entity_regex_does_not_match_lowercase_vi():
    found = extract_proper_nouns_vi("kênh ị ạ ậ không phải tên riêng")
    assert len(found) == 0


def test_entity_regex_vi_standard_capitalization():
    found = extract_proper_nouns_vi("Hà Nội là thị trường chính")
    assert any("Hà" in f for f in found)


# ── Fix 4: Auto-tag disambiguation ────────────────────────────────────

@pytest.fixture
def ambiguous_evidence():
    return EvidenceSet(facts=[
        Fact(fact_id="F1", columns=["val"],
             rows=[{"val": 100.0}, {"val": 101.0}], sql="SELECT ..."),
    ])


def test_auto_tag_skips_ambiguous(ambiguous_evidence):
    text = "Giá trị là 100,5"
    result = _auto_tag_numbers(text, ambiguous_evidence, tol=0.02)
    assert "100,5" in result or "{{" not in result


@pytest.fixture
def unique_evidence():
    return EvidenceSet(facts=[
        Fact(fact_id="F1", columns=["romi"], rows=[{"romi": 6.20}], sql="SELECT ..."),
        Fact(fact_id="F2", columns=["profit"], rows=[{"profit": 392498488.0}], sql="SELECT ..."),
    ])


def test_auto_tag_unique_match(unique_evidence):
    text = "ROMI là 6,20"
    result = _auto_tag_numbers(text, unique_evidence, tol=0.02)
    assert "{{F1.r1.romi}}" in result


# ── Fix 5: Vietnamese number parsing ──────────────────────────────────

def test_parse_vi_comma_decimal():
    assert parse_vi_number("6,20") == 6.20


def test_parse_vi_dot_thousands():
    assert parse_vi_number("392.498.488") == 392498488.0


def test_parse_en_dot_decimal():
    assert parse_vi_number("6.20") == 6.20


def test_parse_en_comma_thousands():
    assert parse_vi_number("392,498,488") == 392498488.0


def test_parse_vi_mixed():
    assert parse_vi_number("392.498.488,50") == 392498488.50


def test_parse_plain_integer():
    assert parse_vi_number("17529774") == 17529774.0


# ── Fix 6: L4 stats guard severity ────────────────────────────────────

@pytest.fixture
def stats_cfg():
    return {"min_sample_size": 30}


def test_stats_guard_unsupported_comparison_warns(stats_cfg):
    ev = EvidenceSet(facts=[], comparisons=[])
    text = "Chiến dịch A cao hơn chiến dịch B đáng kể."
    result = check_stats_guard(text, ev, stats_cfg)
    assert not result.passed
    assert result.severity == Severity.WARN


def test_stats_guard_causal_without_evidence_warns(stats_cfg):
    ev = EvidenceSet(facts=[], comparisons=[])
    text = "Cài app dẫn đến tăng doanh thu."
    result = check_stats_guard(text, ev, stats_cfg)
    assert not result.passed
    assert result.severity == Severity.WARN


def test_stats_guard_clean_text_passes(stats_cfg):
    ev = EvidenceSet(facts=[], comparisons=[])
    text = "Doanh thu tháng này là 100 triệu VND."
    result = check_stats_guard(text, ev, stats_cfg)
    assert result.passed
    assert result.severity == Severity.WARN
