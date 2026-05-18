"""add llm provider operation type

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f7
Create Date: 2026-05-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("llm_providers"):
        return

    if not _has_column("llm_providers", "operation_type"):
        op.add_column(
            "llm_providers",
            sa.Column(
                "operation_type",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'llm'"),
            ),
        )

    op.execute(
        """
        UPDATE llm_providers
        SET operation_type = CASE
            WHEN RIGHT(provider_type, 10) = '_embedding' THEN 'embedding'
            WHEN RIGHT(provider_type, 9) = '_reranker' THEN 'rerank'
            ELSE operation_type
        END
        """
    )

    op.execute(
        """
        INSERT INTO llm_providers (
            id,
            name,
            provider_type,
            operation_type,
            api_key_encrypted,
            base_url,
            llm_model,
            llm_small_model,
            embedding_model,
            reranker_model,
            config,
            is_active,
            is_default,
            is_enabled,
            allowed_models,
            blocked_models,
            pool_weight,
            pool_enabled,
            model_tier,
            secondary_models,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            LEFT(source.name || ' Embedding', 255),
            source.provider_type,
            'embedding',
            source.api_key_encrypted,
            source.base_url,
            NULL,
            NULL,
            source.embedding_model,
            NULL,
            source.config,
            source.is_active,
            source.is_default,
            source.is_enabled,
            source.allowed_models,
            source.blocked_models,
            source.pool_weight,
            FALSE,
            NULL,
            NULL,
            source.created_at,
            source.updated_at
        FROM llm_providers AS source
        WHERE source.operation_type = 'llm'
            AND source.embedding_model IS NOT NULL
            AND source.embedding_model <> ''
            AND NOT EXISTS (
                SELECT 1
                FROM llm_providers AS existing
                WHERE existing.name = LEFT(source.name || ' Embedding', 255)
            )
        """
    )

    op.execute(
        """
        INSERT INTO llm_providers (
            id,
            name,
            provider_type,
            operation_type,
            api_key_encrypted,
            base_url,
            llm_model,
            llm_small_model,
            embedding_model,
            reranker_model,
            config,
            is_active,
            is_default,
            is_enabled,
            allowed_models,
            blocked_models,
            pool_weight,
            pool_enabled,
            model_tier,
            secondary_models,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            LEFT(source.name || ' Rerank', 255),
            source.provider_type,
            'rerank',
            source.api_key_encrypted,
            source.base_url,
            NULL,
            NULL,
            NULL,
            source.reranker_model,
            source.config::jsonb - 'embedding',
            source.is_active,
            source.is_default,
            source.is_enabled,
            source.allowed_models,
            source.blocked_models,
            source.pool_weight,
            FALSE,
            NULL,
            NULL,
            source.created_at,
            source.updated_at
        FROM llm_providers AS source
        WHERE source.operation_type = 'llm'
            AND source.reranker_model IS NOT NULL
            AND source.reranker_model <> ''
            AND NOT EXISTS (
                SELECT 1
                FROM llm_providers AS existing
                WHERE existing.name = LEFT(source.name || ' Rerank', 255)
            )
        """
    )

    op.execute(
        """
        UPDATE tenant_provider_mappings AS mapping
        SET provider_id = embedding_provider.id
        FROM llm_providers AS source
        JOIN llm_providers AS embedding_provider
            ON embedding_provider.name = LEFT(source.name || ' Embedding', 255)
            AND embedding_provider.operation_type = 'embedding'
        WHERE mapping.provider_id = source.id
            AND mapping.operation_type = 'embedding'
            AND source.operation_type = 'llm'
        """
    )

    op.execute(
        """
        UPDATE tenant_provider_mappings AS mapping
        SET provider_id = rerank_provider.id
        FROM llm_providers AS source
        JOIN llm_providers AS rerank_provider
            ON rerank_provider.name = LEFT(source.name || ' Rerank', 255)
            AND rerank_provider.operation_type = 'rerank'
        WHERE mapping.provider_id = source.id
            AND mapping.operation_type = 'rerank'
            AND source.operation_type = 'llm'
        """
    )

    op.execute(
        """
        UPDATE llm_providers
        SET embedding_model = NULL,
            reranker_model = NULL,
            config = config::jsonb - 'embedding'
        WHERE operation_type = 'llm'
        """
    )

    op.execute(
        """
        UPDATE llm_providers
        SET llm_model = NULL,
            llm_small_model = NULL,
            reranker_model = NULL,
            pool_enabled = FALSE,
            model_tier = NULL,
            secondary_models = NULL
        WHERE operation_type = 'embedding'
        """
    )

    op.execute(
        """
        UPDATE llm_providers
        SET llm_model = NULL,
            llm_small_model = NULL,
            embedding_model = NULL,
            config = config::jsonb - 'embedding',
            pool_enabled = FALSE,
            model_tier = NULL,
            secondary_models = NULL
        WHERE operation_type = 'rerank'
        """
    )

    op.execute(
        "ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_operation_type"
    )
    op.execute(
        "ALTER TABLE llm_providers "
        "ADD CONSTRAINT llm_providers_valid_operation_type "
        "CHECK (operation_type IN ('llm', 'embedding', 'rerank'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_providers_operation ON llm_providers (operation_type)"
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("llm_providers"):
        return

    op.execute("DROP INDEX IF EXISTS idx_llm_providers_operation")
    op.execute(
        "ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_operation_type"
    )
    if _has_column("llm_providers", "operation_type"):
        op.drop_column("llm_providers", "operation_type")
