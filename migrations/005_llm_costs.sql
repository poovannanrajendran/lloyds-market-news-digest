CREATE TABLE IF NOT EXISTS llm_cost_calls (
    cost_id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id TEXT,
    candidate_id TEXT,
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    service_tier TEXT,
    tokens_prompt INTEGER NOT NULL,
    tokens_completion INTEGER NOT NULL,
    cost_input_usd NUMERIC(12, 6) NOT NULL,
    cost_output_usd NUMERIC(12, 6) NOT NULL,
    cost_total_usd NUMERIC(12, 6) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS llm_cost_stage_daily (
    usage_date DATE NOT NULL,
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    service_tier TEXT,
    calls INTEGER NOT NULL,
    tokens_prompt INTEGER NOT NULL,
    tokens_completion INTEGER NOT NULL,
    cost_total_usd NUMERIC(12, 6) NOT NULL,
    PRIMARY KEY (usage_date, stage, provider, model, service_tier)
);
