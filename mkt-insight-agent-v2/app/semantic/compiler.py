"""Semantic compiler — MetricRequest → SQL with bind parameters.

R2: NEVER concatenate user data into SQL — always bind parameters.
This is the single most important security guarantee.
"""
from __future__ import annotations

import re
from typing import Any

from app.contracts import MetricRequest
from app.semantic.metrics import get_metric
from app.errors import SemanticCompileError, UnknownMetricError
from app.logging_ import get_logger

_log = get_logger("semantic.compiler")

_FILTER_MAP: dict[str, str] = {
    "campaign_name": "campaign_name = :f_campaign_name",
    "sub_channel": "sub_channel = :f_sub_channel",
    "channel": "channel = :f_channel",
    "segment": "segment_name = :f_segment",
    "product": "product_name = :f_product",
    "date_from": "date >= :f_date_from",
    "date_to": "date <= :f_date_to",
    "status": "status = :f_status",
}


def compile_metric(req: MetricRequest) -> tuple[str, dict[str, Any]]:
    """Compile a MetricRequest into (sql, bind_params).

    The metric's sql_template contains {filter_clause} which we replace with
    AND-joined bind-parameterized conditions. User values NEVER go into the SQL
    string — only into the params dict.
    """
    metric = get_metric(req.metric)
    template: str = metric["sql_template"]

    filter_clauses: list[str] = []
    params: dict[str, Any] = {}

    for key, value in req.filters.items():
        clause_tmpl = _FILTER_MAP.get(key)
        if clause_tmpl is None:
            _log.warning("Unknown filter key ignored: %s", key)
            continue
        bind_name = f"f_{key}"
        filter_clauses.append(clause_tmpl)
        params[bind_name] = value

    filter_clause = " AND ".join(filter_clauses) if filter_clauses else "TRUE"

    if "{filter_clause}" in template:
        sql = template.replace("{filter_clause}", filter_clause)
    elif "{filters}" in template:
        sql = template.replace("{filters}", filter_clause)
    else:
        sql = template

    if not _has_limit(sql) and not metric.get("aggregate_only", False):
        sql = sql.rstrip(";") + " LIMIT 500"

    if not _verify_bind_only(sql):
        raise SemanticCompileError(
            f"Compiled SQL contains literal where bind param expected. Metric: {req.metric}"
        )

    return sql, params


def _has_limit(sql: str) -> bool:
    return bool(re.search(r"\bLIMIT\b", sql, re.IGNORECASE))


def _verify_bind_only(sql: str) -> bool:
    """Verify no single-quoted string literals that look like user data.
    Numeric literals and static schema names are fine.
    """
    for m in re.finditer(r"'([^']*)'", sql):
        literal = m.group(1)
        if literal and not literal.replace(".", "").replace("-", "").isdigit():
            if literal not in ("TRUE", "FALSE", "true", "false"):
                return False
    return True
