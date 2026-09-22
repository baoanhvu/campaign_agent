"""ETL — Load full_schema_mock.xlsx into PostgreSQL raw tables, then build mart.funnel_daily.

Usage: python -m etl.load_excel [--file data/full_schema_mock.xlsx]

Drops all old data, creates new schema (etl/sql/ddl.sql), loads 8 Excel tabs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from app.settings import get_settings
from app.logging_ import setup_logging, get_logger

from dotenv import load_dotenv
load_dotenv()

setup_logging("info")
_log = get_logger("etl,load_excel")

DDL_PATH = Path(__file__).parent / "sql" / "ddl.sql"
DEFAULT_EXCEL = "data/full_schema_mock.xlsx"

TABLE_MAP = {
    "fact_lead": "raw.fact_lead",
    "fact_app_install": "raw.fact_app_install",
    "fact_loan": "raw.fact_loan",
    "fact_reject": "raw.fact_reject",
    "dim_customer": "raw.dim_customer",
    "loan_application_pnl": "raw.loan_application_pnl",
    "fact_digital_footprint": "raw.fact_digital_footprint",
    "fact_lead_cost": "raw.fact_lead_cost",
}

DATE_COLUMNS = {
    "fact_lead": ["create_at"],
    "fact_app_install": ["install_time", "phone_captured_time", "phone_verified_time"],
    "fact_loan": ["create_at", "disbursement_date", "settlement_date"],
    "dim_customer": ["Customer_open_date"],
    "fact_lead_cost": ["cost_date"],
}

INT_COLUMNS = {
    "fact_loan": ["no_paid", "last_dayslate", "max_dayslate", "loan_number_rank"],
}


def run_ddl(eng):
    _log.info("Executing DDL (drop old schema, create new)...")
    ddl = DDL_PATH.read_text(encoding="utf-8")
    with eng.begin() as conn:
        conn.execute(text(ddl))
    _log.info("DDL done")


def load_excel_to_raw(eng, excel_path: str):
    _log.info("Loading Excel: %s", excel_path)
    xl = pd.ExcelFile(excel_path)

    for sheet_name, table_name in TABLE_MAP.items():
        if sheet_name not in xl.sheet_names:
            _log.warning("Sheet '%s' not found, skipping", sheet_name)
            continue

        df = pd.read_excel(xl, sheet_name=sheet_name)
        for col in DATE_COLUMNS.get(sheet_name, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        for col in INT_COLUMNS.get(sheet_name, []):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        df.to_sql(
            table_name.split(".")[-1],
            eng,
            schema=table_name.split(".")[0],
            if_exists="append",
            index=False,
            method="multi",
            chunksize=100,
        )
        _log.info("  %s -> %s (%d rows)", sheet_name, table_name, len(df))

    _log.info("All raw tables loaded")


def build_mart(eng):
    """Build mart.funnel_daily by aggregating raw tables (SQL port of aggregate_real_schema)."""
    _log.info("Building mart.funnel_daily...")
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO mart.funnel_daily (
                date, campaign_name, channel, product,
                ad_spend, reach_count, registered_count, approved_count, rejected_count,
                top_reject_reason, avg_processing_time_hours,
                disbursed_count, disbursed_amount, settled_count, early_settled_count,
                outstanding_balance, interest_income, disbursed_acq_cost,
                avg_reloan_cadence_days,
                install_count, phone_verified_count,
                avg_lead_to_install_hours, avg_install_to_phone_hours, avg_phone_to_apply_hours,
                dropoff_reach_to_register, dropoff_register_to_approve,
                cpl, cpa, cac, avg_loan_value, roi_outstanding, cost_to_disbursed_ratio
            )
            WITH all_dates AS (
                SELECT DISTINCT d::date AS date FROM (
                    SELECT create_at::date AS d FROM raw.fact_lead
                    UNION
                    SELECT create_at::date AS d FROM raw.fact_loan
                ) dates
            ),
            all_channels AS (
                SELECT DISTINCT channel FROM (
                    SELECT channel FROM raw.fact_lead WHERE channel IS NOT NULL
                    UNION
                    SELECT channel FROM raw.fact_loan WHERE channel IS NOT NULL
                ) ch
            ),
            grid AS (
                SELECT d.date, c.channel FROM all_dates d CROSS JOIN all_channels c
            ),
            reach AS (
                SELECT create_at::date AS date, channel, COUNT(*) AS reach_count
                FROM raw.fact_lead GROUP BY 1, 2
            ),
            registered AS (
                SELECT create_at::date AS date, channel, COUNT(*) AS registered_count
                FROM raw.fact_loan GROUP BY 1, 2
            ),
            rejected_ids AS (
                SELECT loan_application_id FROM raw.fact_reject
            ),
            approved AS (
                SELECT create_at::date AS date, channel, COUNT(*) AS approved_count
                FROM raw.fact_loan WHERE application_id NOT IN (SELECT loan_application_id FROM rejected_ids)
                GROUP BY 1, 2
            ),
            rejected_cnt AS (
                SELECT l.create_at::date AS date, l.channel, COUNT(*) AS rejected_count
                FROM raw.fact_loan l JOIN rejected_ids r ON l.application_id = r.loan_application_id
                GROUP BY 1, 2
            ),
            disbursed AS (
                SELECT disbursement_date::date AS date, channel,
                       COUNT(*) AS disbursed_count, SUM(loan_amount) AS disbursed_amount
                FROM raw.fact_loan WHERE disbursement_date IS NOT NULL GROUP BY 1, 2
            ),
            avg_proc AS (
                SELECT disbursement_date::date AS date, channel,
                       AVG(EXTRACT(EPOCH FROM (disbursement_date - create_at)) / 3600) AS avg_processing_time_hours
                FROM raw.fact_loan WHERE disbursement_date IS NOT NULL GROUP BY 1, 2
            ),
            disb_pnl AS (
                SELECT l.disbursement_date::date AS date, l.channel,
                       SUM(l.loan_balance) AS outstanding_balance,
                       SUM(COALESCE(p.interest_income, 0)) AS interest_income,
                       SUM(COALESCE(p.lead_cost, 0) + COALESCE(p.marketing_cost, 0)) AS disbursed_acq_cost
                FROM raw.fact_loan l
                LEFT JOIN raw.loan_application_pnl p ON l.application_id = p.loan_application_id
                WHERE l.disbursement_date IS NOT NULL
                GROUP BY 1, 2
            ),
            settled AS (
                SELECT settlement_date::date AS date, channel, COUNT(*) AS settled_count
                FROM raw.fact_loan WHERE settlement_date IS NOT NULL GROUP BY 1, 2
            ),
            early_settled AS (
                SELECT l.settlement_date::date AS date, l.channel, COUNT(*) AS early_settled_count
                FROM raw.fact_loan l
                JOIN raw.loan_application_pnl p ON l.application_id = p.loan_application_id
                WHERE l.settlement_date IS NOT NULL AND p.early_paid_off_fee > 0
                GROUP BY 1, 2
            ),
            ad_spend AS (
                SELECT cost_date AS date, channel, SUM(lead_cost) AS ad_spend
                FROM raw.fact_lead_cost GROUP BY 1, 2
            ),
            reloan AS (
                SELECT create_at::date AS date, channel, AVG(reloan_cadence_days) AS avg_reloan_cadence_days
                FROM raw.fact_loan WHERE reloan_cadence_days IS NOT NULL GROUP BY 1, 2
            ),
            install AS (
                SELECT install_time::date AS date, channel, COUNT(*) AS install_count
                FROM raw.fact_app_install GROUP BY 1, 2
            ),
            phone_verified AS (
                SELECT install_time::date AS date, channel, COUNT(*) AS phone_verified_count
                FROM raw.fact_app_install WHERE phone_verified_time IS NOT NULL GROUP BY 1, 2
            ),
            avg_install_phone AS (
                SELECT install_time::date AS date, channel,
                       AVG(EXTRACT(EPOCH FROM (phone_verified_time - install_time)) / 3600) AS avg_install_to_phone_hours
                FROM raw.fact_app_install WHERE phone_verified_time IS NOT NULL GROUP BY 1, 2
            ),
            avg_lead_install AS (
                SELECT i.install_time::date AS date, i.channel,
                       AVG(EXTRACT(EPOCH FROM (i.install_time - l.create_at)) / 3600) AS avg_lead_to_install_hours
                FROM raw.fact_app_install i
                JOIN raw.fact_lead l ON i.lead_id = l.lead_id
                GROUP BY 1, 2
            ),
            top_reject AS (
                SELECT l.create_at::date AS date, l.channel,
                       MODE() WITHIN GROUP (ORDER BY r.reason_level_1) AS top_reject_reason
                FROM raw.fact_loan l
                JOIN raw.fact_reject r ON l.application_id = r.loan_application_id
                GROUP BY 1, 2
            ),
            channel_product AS (
                SELECT channel, MODE() WITHIN GROUP (ORDER BY product_name) AS product
                FROM raw.fact_loan WHERE product_name IS NOT NULL GROUP BY 1
            )
            SELECT
                g.date, g.channel AS campaign_name, g.channel,
                COALESCE(cp.product,
                    CASE WHEN g.channel IN (SELECT DISTINCT channel FROM raw.fact_lead WHERE product_id = 'PRD-FL')
                         THEN 'First Loan'
                         WHEN g.channel IN (SELECT DISTINCT channel FROM raw.fact_lead WHERE product_id = 'PRD-RL')
                         THEN 'Re-loan'
                         ELSE 'Khac' END) AS product,
                COALESCE(ads.ad_spend, 0), COALESCE(r.reach_count, 0),
                COALESCE(reg.registered_count, 0), COALESCE(apr.approved_count, 0), COALESCE(rej.rejected_count, 0),
                tr.top_reject_reason, apc.avg_processing_time_hours,
                COALESCE(dis.disbursed_count, 0), COALESCE(dis.disbursed_amount, 0),
                COALESCE(stl.settled_count, 0), COALESCE(es.early_settled_count, 0),
                COALESCE(dp.outstanding_balance, 0), COALESCE(dp.interest_income, 0), COALESCE(dp.disbursed_acq_cost, 0),
                rl.avg_reloan_cadence_days,
                COALESCE(ins.install_count, 0), COALESCE(pv.phone_verified_count, 0),
                ali.avg_lead_to_install_hours, aip.avg_install_to_phone_hours, NULL,
                CASE WHEN COALESCE(r.reach_count, 0) > 0
                     THEN 1.0 - COALESCE(reg.registered_count, 0)::float / r.reach_count ELSE NULL END,
                CASE WHEN COALESCE(reg.registered_count, 0) > 0
                     THEN 1.0 - COALESCE(apr.approved_count, 0)::float / reg.registered_count ELSE NULL END,
                CASE WHEN COALESCE(r.reach_count, 0) > 0
                     THEN COALESCE(ads.ad_spend, 0) / r.reach_count ELSE NULL END,
                CASE WHEN COALESCE(dis.disbursed_count, 0) > 0
                     THEN COALESCE(ads.ad_spend, 0) / dis.disbursed_count ELSE NULL END,
                CASE WHEN COALESCE(dis.disbursed_count, 0) > 0
                     THEN COALESCE(dp.disbursed_acq_cost, 0) / dis.disbursed_count ELSE NULL END,
                CASE WHEN COALESCE(dis.disbursed_count, 0) > 0
                     THEN COALESCE(dis.disbursed_amount, 0) / dis.disbursed_count ELSE NULL END,
                CASE WHEN COALESCE(dp.outstanding_balance, 0) <> 0
                     THEN COALESCE(dp.interest_income, 0) / dp.outstanding_balance ELSE NULL END,
                CASE WHEN COALESCE(dis.disbursed_amount, 0) <> 0
                     THEN COALESCE(ads.ad_spend, 0) / dis.disbursed_amount ELSE NULL END
            FROM grid g
            LEFT JOIN reach r ON g.date = r.date AND g.channel = r.channel
            LEFT JOIN registered reg ON g.date = reg.date AND g.channel = reg.channel
            LEFT JOIN approved apr ON g.date = apr.date AND g.channel = apr.channel
            LEFT JOIN rejected_cnt rej ON g.date = rej.date AND g.channel = rej.channel
            LEFT JOIN disbursed dis ON g.date = dis.date AND g.channel = dis.channel
            LEFT JOIN avg_proc apc ON g.date = apc.date AND g.channel = apc.channel
            LEFT JOIN disb_pnl dp ON g.date = dp.date AND g.channel = dp.channel
            LEFT JOIN settled stl ON g.date = stl.date AND g.channel = stl.channel
            LEFT JOIN early_settled es ON g.date = es.date AND g.channel = es.channel
            LEFT JOIN ad_spend ads ON g.date = ads.date AND g.channel = ads.channel
            LEFT JOIN reloan rl ON g.date = rl.date AND g.channel = rl.channel
            LEFT JOIN install ins ON g.date = ins.date AND g.channel = ins.channel
            LEFT JOIN phone_verified pv ON g.date = pv.date AND g.channel = pv.channel
            LEFT JOIN avg_install_phone aip ON g.date = aip.date AND g.channel = aip.channel
            LEFT JOIN avg_lead_install ali ON g.date = ali.date AND g.channel = ali.channel
            LEFT JOIN top_reject tr ON g.date = tr.date AND g.channel = tr.channel
            LEFT JOIN channel_product cp ON g.channel = cp.channel
        """))

    _log.info("mart.funnel_daily built (%d rows)",
              eng.connect().execute(text("SELECT COUNT(*) FROM mart.funnel_daily")).scalar())


def main():
    parser = argparse.ArgumentParser(description="Load Excel → PostgreSQL")
    parser.add_argument("--file", default=DEFAULT_EXCEL, help="Excel file path")
    args = parser.parse_args()

    if not Path(args.file).exists():
        _log.error("File not found: %s", args.file)
        sys.exit(1)

    s = get_settings()
    if not s.database.url:
        _log.error("DATABASE URL not set. Set MKT_DATABASE__URL in .env")
        sys.exit(1)

    eng = create_engine(s.database.url, pool_pre_ping=True)
    run_ddl(eng)
    load_excel_to_raw(eng, args.file)
    build_mart(eng)
    _log.info("ETL complete!")

    _log.info("Pre-generating LLM insights...")
    try:
        _pre_generate_insights()
    except Exception as exc:
        _log.warning("Pre-generate insights failed (non-fatal): %s", exc)
    _log.info("All done!")


def _pre_generate_insights():
    """Generate LLM insights and save to file for instant dashboard load."""
    import asyncio
    import json
    from pathlib import Path
    from app.analytics.dashboard_metrics import (
        _load_funnel_daily, _generate_llm_insights, _build_view, get_available_dates,
    )

    all_rows = _load_funnel_daily()
    if not all_rows:
        _log.warning("No data for insights")
        return

    as_of_date = max(r["date"] for r in all_rows)
    products = sorted(set(r.get("product", "Tat ca") for r in all_rows
                          if r.get("product") and r["product"] != "Khac"))
    if not products:
        products = ["Tat ca"]

    llm_results = asyncio.run(_generate_llm_insights(products, all_rows, as_of_date))

    views = {}
    for product in products:
        views[product] = _build_view(product, all_rows, as_of_date, llm_results.get(product, {}))

    insights_data = {
        "insights": llm_results,
        "as_of_date": as_of_date,
    }
    insights_file = Path("data/latest_insights.json")
    insights_file.parent.mkdir(parents=True, exist_ok=True)
    insights_file.write_text(json.dumps(insights_data, ensure_ascii=False, default=str), encoding="utf-8")
    _log.info("Insights saved to %s", insights_file)


if __name__ == "__main__":
    main()
