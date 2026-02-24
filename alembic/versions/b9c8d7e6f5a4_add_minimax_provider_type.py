"""add_minimax_provider_type

Revision ID: b9c8d7e6f5a4
Revises: e8f9a0b1c2d3, g1a2b3c4d5e6
Create Date: 2026-02-24 13:35:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = ("e8f9a0b1c2d3", "g1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_provider_type_constraint(include_minimax: bool) -> None:
    provider_values = (
        "'openai', 'dashscope', 'gemini', 'anthropic', 'groq', "
        "'azure_openai', 'cohere', 'mistral', 'bedrock', 'vertex', "
        "'deepseek', 'zai', 'kimi', 'ollama', 'lmstudio'"
    )
    if include_minimax:
        provider_values = (
            "'openai', 'dashscope', 'gemini', 'anthropic', 'groq', "
            "'azure_openai', 'cohere', 'mistral', 'bedrock', 'vertex', "
            "'deepseek', 'minimax', 'zai', 'kimi', 'ollama', 'lmstudio'"
        )
    op.execute(
        f"""
        ALTER TABLE llm_providers
        ADD CONSTRAINT llm_providers_valid_type
        CHECK (provider_type IN ({provider_values}))
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "llm_providers" not in inspector.get_table_names():
        return

    op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
    _add_provider_type_constraint(include_minimax=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "llm_providers" not in inspector.get_table_names():
        return

    # Map unsupported minimax rows to openai for backward compatibility
    # before restoring the older provider-type constraint.
    op.execute(
        """
        UPDATE llm_providers
        SET provider_type = 'openai'
        WHERE provider_type = 'minimax'
        """
    )
    op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
    _add_provider_type_constraint(include_minimax=False)
