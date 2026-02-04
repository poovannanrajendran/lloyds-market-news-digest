CREATE OR REPLACE VIEW llm_cost_daily_summary AS
SELECT
    usage_date,
    provider,
    model,
    service_tier,
    SUM(calls) AS calls,
    SUM(tokens_prompt) AS tokens_prompt,
    SUM(tokens_completion) AS tokens_completion,
    SUM(cost_total_usd) AS cost_total_usd
FROM llm_cost_stage_daily
GROUP BY usage_date, provider, model, service_tier;

CREATE OR REPLACE VIEW llm_cost_stage_summary AS
SELECT
    usage_date,
    stage,
    provider,
    model,
    service_tier,
    calls,
    tokens_prompt,
    tokens_completion,
    cost_total_usd
FROM llm_cost_stage_daily;

CREATE OR REPLACE VIEW llm_cost_calls_recent AS
SELECT
    cost_id,
    created_at,
    stage,
    provider,
    model,
    service_tier,
    tokens_prompt,
    tokens_completion,
    cost_total_usd
FROM llm_cost_calls
ORDER BY created_at DESC;
