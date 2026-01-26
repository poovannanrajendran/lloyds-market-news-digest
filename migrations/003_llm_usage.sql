CREATE TABLE IF NOT EXISTS llm_usage (
    usage_id BIGSERIAL PRIMARY KEY,
    run_id TEXT,
    candidate_id TEXT,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    latency_ms INTEGER,
    tokens_prompt INTEGER,
    tokens_completion INTEGER,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_run_id ON llm_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_candidate_id ON llm_usage(candidate_id);
