"""Test R2: Never concatenate user data into SQL — always bind parameters."""
import pytest
from app.contracts import MetricRequest
from app.semantic.compiler import compile_metric


def test_bind_params_used():
    req = MetricRequest(metric="cpl", filters={"campaign_name": "Zalo Ads"})
    sql, params = compile_metric(req)
    assert ":f_campaign_name" in sql
    assert params["f_campaign_name"] == "Zalo Ads"
    assert "Zalo Ads" not in sql


def test_no_string_literal_injection():
    malicious = "'; DROP TABLE raw.fact_loan; --"
    req = MetricRequest(metric="cpl", filters={"campaign_name": malicious})
    sql, params = compile_metric(req)
    assert malicious not in sql
    assert "DROP" not in sql.upper()
    assert params["f_campaign_name"] == malicious


def test_multiple_filters():
    req = MetricRequest(metric="cpl",
                        filters={"campaign_name": "A", "channel": "B"})
    sql, params = compile_metric(req)
    assert ":f_campaign_name" in sql
    assert ":f_channel" in sql
    assert params == {"f_campaign_name": "A", "f_channel": "B"}


def test_limit_added():
    req = MetricRequest(metric="cpl", filters={})
    sql, params = compile_metric(req)
    assert "GROUP BY" in sql.upper()
    assert "TRUE" in sql.upper()
