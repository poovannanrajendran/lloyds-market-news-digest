CREATE TABLE IF NOT EXISTS domain_method_stats (
    domain TEXT NOT NULL,
    method TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    duration_history JSONB DEFAULT '[]'::jsonb,
    median_duration_ms INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, method)
);

CREATE TABLE IF NOT EXISTS domain_method_prefs (
    domain TEXT PRIMARY KEY,
    primary_method TEXT NOT NULL,
    fallback_methods TEXT[] DEFAULT ARRAY[]::TEXT[],
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_changed_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,
    drift_flag BOOLEAN NOT NULL DEFAULT FALSE,
    drift_notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_method_stats_domain ON domain_method_stats(domain);
