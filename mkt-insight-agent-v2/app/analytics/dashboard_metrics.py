"""Dashboard metrics — compute KPIs, anomalies, funnel from mart.funnel_daily.

SQL-based port of reference repo's metrics.py + dashboard.py.
Outputs the same JSON context structure that dashboard.html expects.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from typing import Any

from app.data.db import execute_ro
from app.logging_ import get_logger

_log = get_logger("analytics.dashboard_metrics")

ROLLING_WINDOW_DAYS = 7
TREND_DAYS = 3

FUNNEL_STEPS = [
    ("reach_count", "1. Tiếp cận"),
    ("registered_count", "2. Đăng ký"),
    ("approved_count", "3. Duyệt đơn"),
    ("disbursed_count", "4. Giải ngân"),
    ("settled_count", "5. Tất toán"),
]

KPI_LABELS = {
    "cpl": "Chi phí mỗi lead (CPL)",
    "cpa": "Chi phí mỗi khoản vay giải ngân (CPA, xấp xỉ)",
    "lead_to_registration_rate": "Tỷ lệ Lead → Đăng ký",
    "approval_rate": "Tỷ lệ duyệt đơn (Đăng ký → Duyệt)",
    "roi_outstanding": "Thu nhập lãi trên dư nợ",
    "early_settlement_rate": "Tỷ lệ tất toán sớm",
    "reach_count": "Số lượng lead tiếp cận",
    "registered_count": "Số hồ sơ đăng ký",
    "approved_count": "Số đơn được duyệt",
    "disbursed_count": "Số đơn giải ngân",
    "disbursed_amount": "Doanh số giải ngân",
}

KPI_DIRECTIONS = {
    "cpl": "cost", "cpa": "cost",
    "lead_to_registration_rate": "conversion", "approval_rate": "conversion",
    "roi_outstanding": "conversion", "early_settlement_rate": "volume",
    "reach_count": "volume", "registered_count": "volume",
    "approved_count": "volume", "disbursed_count": "volume", "disbursed_amount": "volume",
}

KPI_JOURNEY = [
    ("reach_count", "1. Tiếp cận"), ("cpl", "1. Tiếp cận"),
    ("lead_to_registration_rate", "2. Đăng ký"), ("registered_count", "2. Đăng ký"),
    ("approval_rate", "3. Duyệt đơn"), ("approved_count", "3. Duyệt đơn"),
    ("disbursed_count", "4. Giải ngân"), ("disbursed_amount", "4. Giải ngân"), ("cpa", "4. Giải ngân"),
    ("early_settlement_rate", "5. Sau giải ngân"), ("roi_outstanding", "5. Sau giải ngân"),
]
KPI_JOURNEY_INDEX = {kpi: i for i, (kpi, _) in enumerate(KPI_JOURNEY)}
KPI_STAGE = dict(KPI_JOURNEY)
ALWAYS_CHART_KPIS = ["disbursed_amount"]
KPI_UNIT = {"cpl": "vnd", "cpa": "vnd", "disbursed_amount": "vnd_million"}

LEVEL_ORDER = {"critical": 0, "warning": 1, "normal": 2, "chua_du_du_lieu": 3, "khong_ap_dung": 3}
HEADLINE_COLS = [
    "reach_count", "registered_count", "approved_count", "disbursed_count", "disbursed_amount", "ad_spend",
    "disbursed_acq_cost",
]
CONTRIBUTION_METRICS = {
    "disbursed_count": "Số đơn giải ngân",
    "disbursed_amount": "Doanh số giải ngân",
    "registered_count": "Số hồ sơ đăng ký",
    "ad_spend": "Chi phí lead",
}

KPI_COLS = list(KPI_DIRECTIONS.keys())


def _load_funnel_daily() -> list[dict[str, Any]]:
    """Load all rows from mart.funnel_daily."""
    _, rows = execute_ro("""
        SELECT date, campaign_name, channel, product,
               ad_spend, reach_count, registered_count, approved_count, rejected_count,
               top_reject_reason, avg_processing_time_hours,
               disbursed_count, disbursed_amount, settled_count, early_settled_count,
               outstanding_balance, interest_income, disbursed_acq_cost,
               avg_reloan_cadence_days, install_count, phone_verified_count,
               avg_lead_to_install_hours, avg_install_to_phone_hours, avg_phone_to_apply_hours,
               cpl, cpa, cac, avg_loan_value, roi_outstanding, cost_to_disbursed_ratio,
               dropoff_reach_to_register, dropoff_register_to_approve
        FROM mart.funnel_daily ORDER BY campaign_name, date
    """)
    for r in rows:
        if r.get("date"):
            r["date"] = str(r["date"])
    return rows


def _safe_div(a, b):
    if b is None or b == 0 or a is None:
        return None
    return a / b


def _compute_kpis(row: dict) -> dict:
    """Add computed KPI columns to a row."""
    r = dict(row)
    r["cpl"] = _safe_div(r.get("ad_spend"), r.get("reach_count"))
    r["lead_to_registration_rate"] = _safe_div(r.get("registered_count"), r.get("reach_count"))
    r["approval_rate"] = _safe_div(r.get("approved_count"), r.get("registered_count"))
    r["cpa"] = _safe_div(r.get("ad_spend"), r.get("disbursed_count"))
    r["cac"] = _safe_div(r.get("disbursed_acq_cost"), r.get("disbursed_count"))
    r["avg_loan_value"] = _safe_div(r.get("disbursed_amount"), r.get("disbursed_count"))
    r["cost_to_disbursed_ratio"] = _safe_div(r.get("ad_spend"), r.get("disbursed_amount"))
    r["early_settlement_rate"] = _safe_div(r.get("early_settled_count"), r.get("settled_count"))
    r["roi_outstanding"] = _safe_div(r.get("interest_income"), r.get("outstanding_balance"))
    r["dropoff_reach_to_register"] = (
        1 - r["lead_to_registration_rate"] if r["lead_to_registration_rate"] is not None else None
    )
    r["dropoff_register_to_approve"] = (
        1 - r["approval_rate"] if r["approval_rate"] is not None else None
    )
    return r


def _classify(z: float | None, kpi_type: str) -> tuple[str, float]:
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "khong_du_du_lieu", 0.0
    if kpi_type == "cost":
        bad_z = z
    elif kpi_type == "conversion":
        bad_z = -z
    else:
        bad_z = abs(z)
    if bad_z > 2:
        return "critical", bad_z
    if bad_z > 1:
        return "warning", bad_z
    return "normal", bad_z


def _detect_anomalies(kpi_rows: list[dict], as_of_date: str) -> list[dict]:
    """Compare KPIs on as_of_date vs 7-day rolling baseline per channel."""
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for r in kpi_rows:
        by_channel[r["campaign_name"]].append(r)

    records = []
    for channel, rows in by_channel.items():
        rows.sort(key=lambda r: r["date"])
        today_rows = [r for r in rows if r["date"] == as_of_date]
        if not today_rows:
            continue
        today = today_rows[0]
        product = today.get("product", "Tat ca")
        idx_today = next(i for i, r in enumerate(rows) if r["date"] == as_of_date)

        for kpi in KPI_COLS:
            kpi_type = KPI_DIRECTIONS[kpi]
            today_val = today.get(kpi)

            if today_val is None:
                records.append(dict(
                    date=as_of_date, campaign_name=channel, product=product, kpi=kpi,
                    kpi_label=KPI_LABELS[kpi], kpi_type=kpi_type, value=today_val,
                    baseline_mean=None, baseline_std=None, z_score=None, bad_z=None,
                    level="khong_ap_dung", bad_trend_3d=False,
                ))
                continue

            history = [rows[i].get(kpi) for i in range(max(0, idx_today - ROLLING_WINDOW_DAYS), idx_today)]
            history = [v for v in history if v is not None]

            if len(history) < 3:
                records.append(dict(
                    date=as_of_date, campaign_name=channel, product=product, kpi=kpi,
                    kpi_label=KPI_LABELS[kpi], kpi_type=kpi_type, value=today_val,
                    baseline_mean=None, baseline_std=None, z_score=None, bad_z=None,
                    level="chua_du_du_lieu", bad_trend_3d=False,
                ))
                continue

            baseline_mean = statistics.mean(history)
            baseline_std = statistics.pstdev(history)
            if baseline_std == 0:
                z = 0.0 if today_val == baseline_mean else (4.0 if today_val > baseline_mean else -4.0)
            else:
                z = (today_val - baseline_mean) / baseline_std

            level, bad_z = _classify(z, kpi_type)
            records.append(dict(
                date=as_of_date, campaign_name=channel, product=product, kpi=kpi,
                kpi_label=KPI_LABELS[kpi], kpi_type=kpi_type, value=today_val,
                baseline_mean=baseline_mean, baseline_std=baseline_std,
                z_score=z, bad_z=bad_z, level=level, bad_trend_3d=False,
            ))

    return records


def _pct_diff(value, baseline):
    if value is None or baseline is None or baseline == 0:
        return None
    return (value - baseline) / baseline * 100


def _fmt_value(v) -> str:
    if v is None:
        return "-"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"


def _campaign_status(anomalies: list[dict]) -> list[dict]:
    out = []
    by_camp: dict[str, list[dict]] = defaultdict(list)
    for a in anomalies:
        by_camp[a["campaign_name"]].append(a)
    for campaign, items in by_camp.items():
        flagged = [a for a in items if a["level"] in ("critical", "warning")]
        if not flagged:
            out.append(dict(campaign_name=campaign, status="normal", worst_kpi_label=None, worst_bad_z=0.0))
            continue
        worst = max(flagged, key=lambda a: a.get("bad_z", 0) or 0)
        out.append(dict(
            campaign_name=campaign, status=worst["level"],
            worst_kpi_label=worst["kpi_label"], worst_bad_z=float(worst.get("bad_z", 0) or 0),
        ))
    out.sort(key=lambda r: (LEVEL_ORDER.get(r["status"], 9), -r["worst_bad_z"]))
    return out


def _funnel_totals(today_rows: list[dict]) -> list[dict]:
    totals = []
    for col, label in FUNNEL_STEPS:
        total = sum(r.get(col, 0) or 0 for r in today_rows)
        totals.append({"step": label, "count": int(total)})
    return totals


def _funnel_by_campaign(today_rows: list[dict]) -> list[dict]:
    rows = []
    for r in today_rows:
        rows.append(dict(
            campaign_name=r["campaign_name"], channel=r.get("channel", ""),
            steps={col: int(r.get(col, 0) or 0) for col, _ in FUNNEL_STEPS},
            dropoff_reach_to_register=r.get("dropoff_reach_to_register"),
            dropoff_register_to_approve=r.get("dropoff_register_to_approve"),
        ))
    return rows


def _cost_chart_data(today_rows: list[dict]) -> list[dict]:
    rows = []
    for r in today_rows:
        ad_spend = float(r.get("ad_spend", 0) or 0)
        disbursed = float(r.get("disbursed_amount", 0) or 0)
        ratio = round(disbursed / ad_spend, 1) if ad_spend else None
        rows.append(dict(
            campaign_name=r["campaign_name"],
            cpl=round(float(r.get("cpl", 0) or 0), 0) if r.get("cpl") else None,
            cpa=round(float(r.get("cpa", 0) or 0), 0) if r.get("cpa") else None,
            ad_spend=round(ad_spend, 0), disbursed_amount=round(disbursed, 0),
            revenue_to_cost_ratio=ratio,
        ))
    return rows


def _kpi_trend_charts(all_rows: list[dict], anomalies: list[dict], as_of_date: str,
                      max_kpis: int = 8, days: int = 30) -> list[dict]:
    flagged = [a for a in anomalies if a["level"] in ("critical", "warning")]
    if not flagged:
        return []

    kpi_worst: dict[str, float] = defaultdict(float)
    for a in flagged:
        kpi_worst[a["kpi"]] = max(kpi_worst[a["kpi"]], a.get("bad_z", 0) or 0)
    chosen = set(sorted(kpi_worst, key=lambda k: kpi_worst[k], reverse=True)[:max_kpis]) | set(ALWAYS_CHART_KPIS)
    top_kpis = sorted(chosen, key=lambda k: KPI_JOURNEY_INDEX.get(k, 99))

    window = [r for r in all_rows if r["date"] <= as_of_date]
    all_dates = sorted(set(r["date"] for r in window))[-days:]
    window = [r for r in window if r["date"] in all_dates]

    charts = []
    for kpi in top_kpis:
        kpi_label = KPI_LABELS[kpi]
        kpi_type = KPI_DIRECTIONS[kpi]
        flagged_by_channel = {a["campaign_name"]: a["level"] for a in flagged if a["kpi"] == kpi}

        by_channel: dict[str, list[dict]] = defaultdict(list)
        for r in window:
            by_channel[r["campaign_name"]].append(r)

        series = []
        for channel, ch_rows in by_channel.items():
            ch_rows.sort(key=lambda r: r["date"])
            date_map = {r["date"]: r.get(kpi) for r in ch_rows}
            values = [date_map.get(d) for d in all_dates]
            values = [None if v is None else round(float(v), 4) for v in values]
            series.append(dict(
                channel=channel, values=values,
                level=flagged_by_channel.get(channel, "normal"),
            ))
        charts.append(dict(
            kpi=kpi, kpi_label=kpi_label, kpi_type=kpi_type,
            stage=KPI_STAGE.get(kpi, ""), unit=KPI_UNIT.get(kpi, ""),
            dates=all_dates, series=series,
        ))
    return charts


def _anomalies_table(anomalies: list[dict]) -> list[dict]:
    flagged = [a for a in anomalies if a["level"] in ("warning", "critical")]
    flagged.sort(key=lambda a: (LEVEL_ORDER.get(a["level"], 9), -(a.get("bad_z", 0) or 0)))
    return [dict(campaign_name=a["campaign_name"], kpi_label=a["kpi_label"], level=a["level"]) for a in flagged]


def _journey_by_campaign(today_rows: list[dict], product: str) -> list[dict]:
    cols = (
        ["install_count", "phone_verified_count",
         "avg_lead_to_install_hours", "avg_install_to_phone_hours", "avg_phone_to_apply_hours"]
        if product == "First Loan" else ["avg_reloan_cadence_days"]
    )
    rows = []
    for r in today_rows:
        row = {"campaign_name": r["campaign_name"]}
        for c in cols:
            v = r.get(c)
            row[c] = None if v is None else float(v)
        rows.append(row)
    return rows


def _headline_by_channel(all_rows: list[dict], as_of_date: str) -> list[dict]:
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        by_channel[r["campaign_name"]].append(r)

    rows = []
    for channel, ch_rows in by_channel.items():
        ch_rows.sort(key=lambda r: r["date"])
        prior = [r for r in ch_rows if r["date"] < as_of_date]
        prev_date = prior[-1]["date"] if prior else None
        base_dates = set(r["date"] for r in prior[-ROLLING_WINDOW_DAYS:])

        def _totals(rows_subset, agg):
            if not rows_subset:
                return None
            result = {}
            for c in HEADLINE_COLS:
                vals = [r.get(c, 0) or 0 for r in rows_subset]
                result[c] = sum(vals) if agg == "sum" else (sum(vals) / len(vals) if vals else 0)
            return result

        today_r = [r for r in ch_rows if r["date"] == as_of_date]
        prev_r = [r for r in ch_rows if r["date"] == prev_date] if prev_date else []
        base_r = [r for r in ch_rows if r["date"] in base_dates]

        rows.append(dict(
            campaign_name=channel,
            today=_totals(today_r, "sum"),
            prev=_totals(prev_r, "sum") if prev_r else None,
            base7=_totals(base_r, "mean"),
        ))
    return rows


def _quick_summary(anomalies: list[dict], llm_result: dict) -> dict:
    highlights = {h.get("campaign_name"): h.get("insight_1_cau")
                  for h in (llm_result.get("critical_highlights") or [])}

    top_issues = []
    flagged = [a for a in anomalies if a["level"] in ("critical", "warning")]
    flagged.sort(key=lambda a: -(a.get("bad_z", 0) or 0))
    for r in flagged[:3]:
        reason = highlights.pop(r["campaign_name"], None)
        if not reason:
            pct = _pct_diff(r["value"], r["baseline_mean"])
            if pct is None:
                reason = f"{_fmt_value(r['value'])} — chênh lệch đáng kể so với mức thường ngày"
            else:
                word = "cao hơn" if pct > 0 else "thấp hơn"
                reason = f"{_fmt_value(r['value'])} — {word} {abs(pct):.0f}% so với mức thường ngày"
        top_issues.append(dict(
            campaign_name=r["campaign_name"], kpi_label=r["kpi_label"],
            level=r["level"], reason=reason,
        ))

    suggestions = llm_result.get("suggestions") or []
    top_suggestions = [s for s in suggestions if s.get("uu_tien") == "cao"][:3]
    return dict(top_issues=top_issues, top_suggestions=top_suggestions)


def _compute_contributions(all_rows: list[dict], as_of_date: str) -> dict:
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        by_channel[r["campaign_name"]].append(r)

    if len(by_channel) < 2:
        return {}

    prior_dates = sorted(set(r["date"] for r in all_rows if r["date"] < as_of_date))
    base_dates = set(prior_dates[-ROLLING_WINDOW_DAYS:])

    out = {}
    for col, label in CONTRIBUTION_METRICS.items():
        today_vals = {}
        base_vals = {}
        for ch, rows in by_channel.items():
            today_r = [r for r in rows if r["date"] == as_of_date]
            base_r = [r for r in rows if r["date"] in base_dates]
            today_vals[ch] = sum((r.get(col, 0) or 0) for r in today_r)
            base_vals[ch] = (sum((r.get(col, 0) or 0) for r in base_r) / len(base_r)) if base_r else 0

        delta = {ch: today_vals[ch] - base_vals.get(ch, 0) for ch in today_vals}
        total_delta = sum(delta.values())
        total_base = sum(base_vals.values())
        share_ok = total_base > 0 and abs(total_delta) >= 0.01 * total_base

        rows_sorted = sorted(delta.items(), key=lambda x: abs(x[1]), reverse=True)
        theo_kenh = [
            dict(campaign_name=ch, hom_nay=today_vals[ch], tb_7_ngay=base_vals.get(ch, 0),
                 thay_doi=d,
                 ty_trong_pct=round(d / total_delta * 100, 1) if share_ok and total_delta != 0 else None)
            for ch, d in rows_sorted
        ]
        out[col] = dict(
            col=col, label=label, tong_hom_nay=sum(today_vals.values()),
            tong_tb_7_ngay=total_base, tong_thay_doi=total_delta,
            tong_thay_doi_pct=round(total_delta / total_base * 100, 1) if total_base > 0 else None,
            theo_kenh=theo_kenh,
        )
    return out


def _build_view(product: str, all_rows: list[dict], as_of_date: str, llm_result: dict) -> dict:
    product_rows = [r for r in all_rows if r.get("product") == product]
    kpi_rows = [_compute_kpis(r) for r in product_rows]
    today_rows = [r for r in kpi_rows if r["date"] == as_of_date]
    anomalies = _detect_anomalies(kpi_rows, as_of_date)
    contributions = _compute_contributions(kpi_rows, as_of_date)

    return dict(
        product=product,
        contributions=list(contributions.values()),
        quick_summary=_quick_summary(anomalies, llm_result),
        campaigns_status=_campaign_status(anomalies),
        funnel_step_defs=[{"col": col, "label": label} for col, label in FUNNEL_STEPS],
        funnel_totals=_funnel_totals(today_rows),
        funnel_by_campaign=_funnel_by_campaign(today_rows),
        headline_by_channel=_headline_by_channel(kpi_rows, as_of_date),
        kpi_trend_charts=_kpi_trend_charts(kpi_rows, anomalies, as_of_date),
        cost_chart=_cost_chart_data(today_rows),
        anomalies_table=_anomalies_table(anomalies),
        journey_by_campaign=_journey_by_campaign(today_rows, product),
        overview_text=llm_result.get("tong_quan"),
        bottlenecks=llm_result.get("diem_nghen") or [],
        cost_text=llm_result.get("hieu_qua_chi_phi"),
        insight_marketing=llm_result.get("insight_marketing") or [],
        insight_sale=llm_result.get("insight_sale") or [],
        suggestions=llm_result.get("suggestions") or [],
        critical_highlights=llm_result.get("critical_highlights") or [],
    )


async def _generate_llm_insights(products: list[str], all_rows: list[dict],
                                 as_of_date: str) -> dict[str, dict]:
    """Call LLM to generate insights for each product in parallel (Hướng A)."""
    from app.llm.insight import interpret_daily
    import asyncio

    async def _one(product: str) -> tuple[str, dict]:
        product_rows = [r for r in all_rows if r.get("product") == product]
        kpi_rows = [_compute_kpis(r) for r in product_rows]
        today_rows = [r for r in kpi_rows if r["date"] == as_of_date]
        anomalies = _detect_anomalies(kpi_rows, as_of_date)
        contributions = _compute_contributions(kpi_rows, as_of_date)
        try:
            result = await asyncio.wait_for(
                interpret_daily(as_of_date, product, today_rows, anomalies, contributions),
                timeout=120,
            )
        except asyncio.TimeoutError:
            result = dict({"tong_quan": "LLM phản hồi quá chậm, xem số liệu thô bên dưới."})
        except Exception:
            result = dict({"tong_quan": "LLM lỗi, xem số liệu thô bên dưới."})
        return product, result

    pairs = await asyncio.gather(*[_one(p) for p in products])
    return dict(pairs)


def get_available_dates() -> list[str]:
    """Return all distinct dates in mart.funnel_daily, newest first."""
    _, rows = execute_ro("SELECT DISTINCT date FROM mart.funnel_daily ORDER BY date DESC")
    return [str(r["date"]) for r in rows if r.get("date")]
