"""add_operation_type_mapping_and_local_providers

Revision ID: f1a2b3c4d5e6
Revises: b333c8709d75
Create Date: 2026-02-19 13:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b333c8709d75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Expand provider type check constraint to include kimi/ollama/lmstudio.
    if "llm_providers" in inspector.get_table_names():
        op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
        op.execute(
            """
            ALTER TABLE llm_providers
            ADD CONSTRAINT llm_providers_valid_type
            CHECK (
                provider_type IN (
                    'openai', 'qwen', 'gemini', 'anthropic', 'groq',
                    'azure_openai', 'cohere', 'mistral', 'bedrock',
                    'vertex', 'deepseek', 'zai', 'kimi', 'ollama', 'lmstudio'
                )
            )
            """
        )

    # Add operation_type for operation-specific provider routing.
    table_name = "tenant_provider_mappings"
    if table_name in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "operation_type" not in columns:
            op.add_column(
                table_name,
                sa.Column("operation_type", sa.String(length=20), server_default="llm", nullable=True),
            )
            op.execute(
                """
                UPDATE tenant_provider_mappings
                SET operation_type = 'llm'
                WHERE operation_type IS NULL
                """
            )
            op.alter_column(table_name, "operation_type", server_default=None, nullable=False)

        # Replace old unique constraint with operation-aware uniqueness.
        op.execute(
            """
            ALTER TABLE tenant_provider_mappings
            DROP CONSTRAINT IF EXISTS tenant_provider_mappings_unique_tenant_provider
            """
        )
        op.execute(
            """
            ALTER TABLE tenant_provider_mappings
            DROP CONSTRAINT IF EXISTS tenant_provider_mappings_unique_tenant_provider_op
            """
        )
        op.execute(
            """
            ALTER TABLE tenant_provider_mappings
            ADD CONSTRAINT tenant_provider_mappings_unique_tenant_provider_op
            UNIQUE (tenant_id, provider_id, operation_type)
            """
        )
        op.execute(
            """
            ALTER TABLE tenant_provider_mappings
            DROP CONSTRAINT IF EXISTS tenant_provider_mappings_valid_operation
            """
        )
        op.execute(
            """
            ALTER TABLE tenant_provider_mappings
            ADD CONSTRAINT tenant_provider_mappings_valid_operation
            CHECK (operation_type IN ('llm', 'embedding', 'rerank'))
            """
        )
        indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        if "idx_tenant_mappings_operation" not in indexes:
            op.create_index(
                "idx_tenant_mappings_operation",
                table_name,
                ["operation_type"],
                unique=False,
            )

        # Backfill existing tenant mappings so all operations initially map to prior provider.
        op.execute(
            """
            INSERT INTO tenant_provider_mappings (tenant_id, provider_id, operation_type, priority, created_at)
            SELECT t.tenant_id, t.provider_id, 'embedding', t.priority, t.created_at
            FROM tenant_provider_mappings t
            WHERE t.operation_type = 'llm'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tenant_provider_mappings e
                  WHERE e.tenant_id = t.tenant_id
                    AND e.provider_id = t.provider_id
                    AND e.operation_type = 'embedding'
              )
            """
        )
        op.execute(
            """
            INSERT INTO tenant_provider_mappings (tenant_id, provider_id, operation_type, priority, created_at)
            SELECT t.tenant_id, t.provider_id, 'rerank', t.priority, t.created_at
            FROM tenant_provider_mappings t
            WHERE t.operation_type = 'llm'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tenant_provider_mappings r
                  WHERE r.tenant_id = t.tenant_id
                    AND r.provider_id = t.provider_id
                    AND r.operation_type = 'rerank'
              )
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Remove backfilled operation mappings first.
    table_name = "tenant_provider_mappings"
    if table_name in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "operation_type" in columns:
            op.execute(
                """
                DELETE FROM tenant_provider_mappings
                WHERE operation_type IN ('embedding', 'rerank')
                """
            )
            indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            if "idx_tenant_mappings_operation" in indexes:
                op.drop_index("idx_tenant_mappings_operation", table_name=table_name)
            op.execute(
                """
                ALTER TABLE tenant_provider_mappings
                DROP CONSTRAINT IF EXISTS tenant_provider_mappings_valid_operation
                """
            )
            op.execute(
                """
                ALTER TABLE tenant_provider_mappings
                DROP CONSTRAINT IF EXISTS tenant_provider_mappings_unique_tenant_provider_op
                """
            )
            op.execute(
                """
                ALTER TABLE tenant_provider_mappings
                DROP CONSTRAINT IF EXISTS tenant_provider_mappings_unique_tenant_provider
                """
            )
            op.execute(
                """
                ALTER TABLE tenant_provider_mappings
                ADD CONSTRAINT tenant_provider_mappings_unique_tenant_provider
                UNIQUE (tenant_id, provider_id)
                """
            )
            op.drop_column(table_name, "operation_type")

    # Restore provider type check constraint.
    if "llm_providers" in inspector.get_table_names():
        op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
        op.execute(
            """
            ALTER TABLE llm_providers
            ADD CONSTRAINT llm_providers_valid_type
            CHECK (
                provider_type IN (
                    'openai', 'qwen', 'gemini', 'anthropic', 'groq',
                    'azure_openai', 'cohere', 'mistral', 'bedrock',
                    'vertex', 'deepseek', 'zai'
                )
            )
            """
        )
