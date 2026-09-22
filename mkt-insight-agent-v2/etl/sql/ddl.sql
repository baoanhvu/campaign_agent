-- etl/sql/ddl.sql — Schema DDL for raw.*, mart.*, ops.*
-- Replaced old schema with 8-table lending campaign schema (from reference repo).

-- ===== CLEAN OLD SCHEMA =====
DROP SCHEMA IF EXISTS raw CASCADE;
DROP SCHEMA IF EXISTS mart CASCADE;
CREATE SCHEMA raw;
CREATE SCHEMA mart;
CREATE SCHEMA IF NOT EXISTS ops;

-- ===== RAW SCHEMA (8 tables from Excel) =====

CREATE TABLE raw.fact_lead (
    lead_id       TEXT PRIMARY KEY,
    "Customer_id" TEXT,
    partner_code  TEXT,
    channel       TEXT NOT NULL,
    sub_channel   TEXT,
    create_at     TIMESTAMP NOT NULL,
    product_id    TEXT,
    campaign_id   TEXT,
    campaign_name TEXT,
    utm_source    TEXT,
    utm_medium    TEXT
);

CREATE TABLE raw.fact_app_install (
    install_id           TEXT PRIMARY KEY,
    install_time         TIMESTAMP NOT NULL,
    channel              TEXT NOT NULL,
    phone_captured_time  TIMESTAMP,
    phone_verified_time  TIMESTAMP,
    lead_id              TEXT
);

CREATE TABLE raw.fact_loan (
    application_id        TEXT PRIMARY KEY,
    "Customer_id"           TEXT NOT NULL,
    product_id            TEXT,
    product_name          TEXT,
    create_at             TIMESTAMP NOT NULL,
    disbursement_date     TIMESTAMP,
    settlement_date       TIMESTAMP,
    partner_code          TEXT,
    channel               TEXT,
    sub_channel           TEXT,
    tenure                DOUBLE PRECISION,
    no_paid               INTEGER,
    last_duedate          DATE,
    last_dayslate         INTEGER,
    max_dayslate          INTEGER,
    nominal_interest_rate DOUBLE PRECISION,
    loan_amount           DOUBLE PRECISION,
    loan_number_rank     INTEGER,
    loan_balance          DOUBLE PRECISION,
    reloan_cadence_days   DOUBLE PRECISION
);

CREATE TABLE raw.fact_reject (
    loan_application_id TEXT PRIMARY KEY,
    reason_level_1      TEXT,
    reason_level_2      TEXT
);

CREATE TABLE raw.dim_customer (
    customer_id       TEXT PRIMARY KEY,
    "Age"               DOUBLE PRECISION,
    "Customer_open_date" DATE,
    occupation        TEXT,
    active_status     TEXT,
    has_app           TEXT,
    income            DOUBLE PRECISION
);

CREATE TABLE raw.loan_application_pnl (
    loan_application_id  TEXT PRIMARY KEY,
    interest_income      DOUBLE PRECISION,
    overdue_interest     DOUBLE PRECISION,
    early_paid_off_fee   DOUBLE PRECISION,
    loan_processing_cost DOUBLE PRECISION,
    funding_cost         DOUBLE PRECISION,
    lead_cost            DOUBLE PRECISION,
    credit_loss          DOUBLE PRECISION,
    operation_cost       DOUBLE PRECISION,
    marketing_cost       DOUBLE PRECISION,
    "Processing_Fee"       DOUBLE PRECISION,
    "Partner_Fee"          DOUBLE PRECISION,
    "Collection_Cost"      DOUBLE PRECISION
);

CREATE TABLE raw.fact_digital_footprint (
    loan_application_id   TEXT PRIMARY KEY,
    device_os             TEXT,
    device_price_segment  TEXT,
    form_filling_time     DOUBLE PRECISION,
    ip_address            TEXT,
    geo_location_match    TEXT
);

CREATE TABLE raw.fact_lead_cost (
    cost_date     DATE NOT NULL,
    channel       TEXT NOT NULL,
    campaign_id   TEXT,
    campaign_name TEXT,
    lead_cost     DOUBLE PRECISION NOT NULL
);

-- ===== MART SCHEMA =====

-- funnel_daily: 1 row = 1 date × 1 channel (aggregated from raw tables)
-- Replicates aggregate_real_schema() from reference repo in SQL.
CREATE TABLE mart.funnel_daily (
    date                            DATE NOT NULL,
    campaign_name                   TEXT NOT NULL,
    channel                         TEXT NOT NULL,
    product                         TEXT,
    ad_spend                        DOUBLE PRECISION DEFAULT 0,
    reach_count                     INTEGER DEFAULT 0,
    registered_count                INTEGER DEFAULT 0,
    approved_count                  INTEGER DEFAULT 0,
    rejected_count                  INTEGER DEFAULT 0,
    top_reject_reason               TEXT,
    avg_processing_time_hours       DOUBLE PRECISION,
    disbursed_count                 INTEGER DEFAULT 0,
    disbursed_amount                DOUBLE PRECISION DEFAULT 0,
    settled_count                   INTEGER DEFAULT 0,
    early_settled_count             INTEGER DEFAULT 0,
    outstanding_balance             DOUBLE PRECISION DEFAULT 0,
    interest_income                 DOUBLE PRECISION DEFAULT 0,
    disbursed_acq_cost              DOUBLE PRECISION DEFAULT 0,
    avg_reloan_cadence_days         DOUBLE PRECISION,
    install_count                   INTEGER DEFAULT 0,
    phone_verified_count            INTEGER DEFAULT 0,
    avg_lead_to_install_hours       DOUBLE PRECISION,
    avg_install_to_phone_hours      DOUBLE PRECISION,
    avg_phone_to_apply_hours        DOUBLE PRECISION,
    dropoff_reach_to_register       DOUBLE PRECISION,
    dropoff_register_to_approve     DOUBLE PRECISION,
    cpl                             DOUBLE PRECISION,
    cpa                             DOUBLE PRECISION,
    cac                             DOUBLE PRECISION,
    avg_loan_value                  DOUBLE PRECISION,
    roi_outstanding                 DOUBLE PRECISION,
    cost_to_disbursed_ratio         DOUBLE PRECISION,
    UNIQUE(date, channel)
);

-- ===== OPS SCHEMA (keep existing) =====
CREATE TABLE IF NOT EXISTS ops.agent_trace (
    trace_id      TEXT PRIMARY KEY,
    question      TEXT,
    intent        TEXT,
    decision      TEXT,
    trust_score   DOUBLE PRECISION,
    trust_band    TEXT,
    checks        JSONB,
    prompt_version TEXT,
    model_name    TEXT,
    profile       TEXT,
    llm_calls     INTEGER,
    latency_ms    INTEGER,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.answer_cache (
    cache_key    TEXT PRIMARY KEY,
    question     TEXT,
    answer       TEXT,
    trust_score  DOUBLE PRECISION,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.dq_results (
    check_id    TEXT,
    description TEXT,
    status      TEXT,
    level       TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.conversations (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.chat_messages (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES ops.conversations(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON ops.chat_messages(session_id, created_at);
