-- =============================================================================
-- PostgreSQL Initialization Script - Enable pgvector Extension
-- =============================================================================
-- This script enables the pgvector extension required for vector similarity
-- search functionality in MemStack.
--
-- The script is automatically executed when the PostgreSQL container starts
-- for the first time (via docker-compose volumes configuration).
-- =============================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension is installed
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE NOTICE 'pgvector extension enabled successfully';
    ELSE
        RAISE WARNING 'pgvector extension was not enabled';
    END IF;
END
$$;
