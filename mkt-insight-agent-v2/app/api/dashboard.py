"""Dashboard routes — serves dashboard context JSON for the new Dashboard page."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.logging_ import get_logger

router = APIRouter()
_log = get_logger("api.dashboard")

_context_cache: dict[str, dict] = {}
_insight_cache: dict[str, dict] = {}
_INSIGHTS_FILE = Path("data/latest_insights.json")


@router.get("/data")
async def dashboard_data(date: str | None = Query(default=None)):
    """Return dashboard data (fast — no LLM). Insights loaded separately via /insights."""
    cache_key = date or "_latest"
    if cache_key in _context_cache:
        return _context_cache[cache_key]

    try:
        from app.analytics.dashboard_metrics import (
            get_available_dates, _load_funnel_daily, _build_view,
        )
        all_rows = _load_funnel_daily()
        if not all_rows:
            return {"as_of_date": "", "tab_labels": [], "views": {}, "available_dates": []}

        if date:
            if not any(r["date"] == date for r in all_rows):
                return {"as_of_date": date, "tab_labels": [], "views": {},
                        "available_dates": get_available_dates(),
                        "error": f"No data for date {date}"}
            as_of_date = date
        else:
            as_of_date = max(r["date"] for r in all_rows)

        products = sorted(set(r.get("product", "Tat ca") for r in all_rows
                              if r.get("product") and r["product"] != "Khac"))
        if not products:
            products = ["Tat ca"]

        views = {}
        for product in products:
            views[product] = _build_view(product, all_rows, as_of_date, {})

        context = dict(as_of_date=as_of_date, tab_labels=products, views=views,
                        available_dates=get_available_dates())
        _context_cache[cache_key] = context
        return context
    except Exception as exc:
        _log.error("dashboard data failed: %s", exc)
        return JSONResponse(
            {"error": str(exc), "as_of_date": "", "tab_labels": [], "views": {}, "available_dates": []},
            status_code=503,
        )


@router.get("/insights")
async def dashboard_insights(date: str | None = Query(default=None)):
    """Return LLM insights for each product.

    Priority: in-memory cache → file cache → real-time generation.
    """
    cache_key = date or "_latest"

    if cache_key in _insight_cache:
        return _insight_cache[cache_key]

    if _INSIGHTS_FILE.exists():
        try:
            file_data = json.loads(_INSIGHTS_FILE.read_text(encoding="utf-8"))
            file_date = file_data.get("as_of_date")
            if not date or file_date == date:
                _insight_cache[cache_key] = file_data
                return file_data
        except Exception:
            pass

    try:
        from app.analytics.dashboard_metrics import (
            _load_funnel_daily, _generate_llm_insights,
        )
        all_rows = _load_funnel_daily()
        if not all_rows:
            return {"insights": {}}

        as_of_date = date or max(r["date"] for r in all_rows)
        if not any(r["date"] == as_of_date for r in all_rows):
            return {"insights": {}, "error": f"No data for {as_of_date}"}

        products = sorted(set(r.get("product", "Tat ca") for r in all_rows
                              if r.get("product") and r["product"] != "Khac"))
        if not products:
            products = ["Tat ca"]

        llm_results = await _generate_llm_insights(products, all_rows, as_of_date)
        result = {"insights": llm_results, "as_of_date": as_of_date}

        _insight_cache[cache_key] = result
        try:
            _INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _INSIGHTS_FILE.write_text(
                json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception:
            pass
        return result
    except Exception as exc:
        _log.error("dashboard insights failed: %s", exc)
        return JSONResponse({"insights": {}, "error": str(exc)}, status_code=503)
