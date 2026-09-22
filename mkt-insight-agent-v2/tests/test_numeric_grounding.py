"""Test R1: LLM never computes a number — numeric grounding (PCN)."""
import pytest
from app.contracts import EvidenceSet, Fact
from app.verify.numeric import check_numeric_grounding
from app.verify.config import load_verify_config


@pytest.fixture
def evidence():
    return EvidenceSet(facts=[
        Fact(fact_id="F1", columns=["campaign_name", "romi"],
             rows=[{"campaign_name": "Zalo Ads", "romi": 1.31}],
             sql="SELECT ...", metric="campaign_romi"),
    ])


@pytest.fixture
def cfg():
    return load_verify_config().get("numeric", {})


def test_tag_resolves(evidence, cfg):
    text = "ROMI là {{F1.r1.romi}}"
    result = check_numeric_grounding(text, evidence, cfg)
    assert result.passed
    assert result.score == 1.0


def test_bare_number_fails(evidence, cfg):
    text = "ROMI là 2,4"
    result = check_numeric_grounding(text, evidence, cfg)
    assert not result.passed
    assert len(result.details["bare_numbers"]) > 0


def test_unresolved_tag_fails(evidence, cfg):
    text = "ROMI là {{F2.r1.romi}}"
    result = check_numeric_grounding(text, evidence, cfg)
    assert not result.passed
    assert "F2.r1.romi" in result.details["unresolved_tags"]


def test_allowlisted_number_passes(evidence, cfg):
    text = "Năm 2026, có 1 chiến dịch"
    result = check_numeric_grounding(text, evidence, cfg)
    assert result.passed
