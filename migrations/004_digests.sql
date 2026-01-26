CREATE TABLE IF NOT EXISTS digests (
    digest_id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    output_path TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_digests_run_date ON digests(run_date);
