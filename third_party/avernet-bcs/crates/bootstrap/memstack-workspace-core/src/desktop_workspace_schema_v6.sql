ALTER TABLE workspace_agent_runtime_correlations
    ADD COLUMN provider_event_hash TEXT
        CHECK (
            provider_event_hash IS NULL
            OR (
                length(provider_event_hash) = 64
                AND provider_event_hash NOT GLOB '*[^0-9a-f]*'
            )
        );

ALTER TABLE workspace_agent_runtime_correlations
    ADD COLUMN provider_event_ingested_at TEXT
        CHECK (
            provider_event_ingested_at IS NULL
            OR provider_event_hash IS NOT NULL
        );

CREATE INDEX IF NOT EXISTS ix_avn_workspace_runtime_provider_event_ingest
    ON workspace_agent_runtime_correlations
        (provider_run_id, provider_event_hash, provider_event_ingested_at);
