CREATE TABLE IF NOT EXISTS run_phase_timings (
    phase_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_phase_timings_run_id ON run_phase_timings(run_id);
CREATE INDEX IF NOT EXISTS idx_phase_timings_phase ON run_phase_timings(phase);
