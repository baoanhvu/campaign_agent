-- etl/sql/marts.sql — Build marts from raw.*

INSERT INTO mart.campaign_performance (campaign_name, sub_channel, spend, revenue, leads, profiles, approvals, disbursements)
SELECT c.campaign_name, c.sub_channel, c.budget AS spend,
       COALESCE(SUM(f.loan_amount) FILTER (WHERE f.status = 'DISBURSED'), 0) AS revenue,
       COUNT(*) AS leads,
       COUNT(*) FILTER (WHERE f.status IN ('APPROVED','REJECTED','DISBURSED')) AS profiles,
       COUNT(*) FILTER (WHERE f.status = 'APPROVED') AS approvals,
       COUNT(*) FILTER (WHERE f.status = 'DISBURSED') AS disbursements
FROM raw.dim_campaign c
LEFT JOIN raw.fact_loan f ON f.sub_channel = c.sub_channel
GROUP BY c.campaign_name, c.sub_channel, c.budget
ON CONFLICT DO NOTHING;

INSERT INTO mart.customer_segments (customer_id, segment_name, clv, loan_count, is_active)
SELECT customer_id, segment_name, clv, loan_count, is_active
FROM raw.dim_customer
ON CONFLICT DO NOTHING;

INSERT INTO mart.loan_profit (loan_id, customer_id, net_profit, sub_channel, date)
SELECT f.loan_id, f.customer_id,
       COALESCE(f.loan_amount * f.rate * f.tenure / 12, 0) - COALESCE(f.balance * 0.05, 0) AS net_profit,
       f.sub_channel, f.date
FROM raw.fact_loan f
WHERE f.status = 'DISBURSED'
ON CONFLICT DO NOTHING;
