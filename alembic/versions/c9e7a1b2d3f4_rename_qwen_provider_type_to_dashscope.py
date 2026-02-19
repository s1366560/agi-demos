"""rename_qwen_provider_type_to_dashscope

Revision ID: c9e7a1b2d3f4
Revises: f1a2b3c4d5e6
Create Date: 2026-02-19 15:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e7a1b2d3f4"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_provider_type_constraint_dashscope() -> None:
    op.execute(
        """
        ALTER TABLE llm_providers
        ADD CONSTRAINT llm_providers_valid_type
        CHECK (
            provider_type IN (
                'openai', 'dashscope', 'gemini', 'anthropic', 'groq',
                'azure_openai', 'cohere', 'mistral', 'bedrock',
                'vertex', 'deepseek', 'zai', 'kimi', 'ollama', 'lmstudio'
            )
        )
        """
    )


def _add_provider_type_constraint_qwen() -> None:
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


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "llm_providers" not in inspector.get_table_names():
        return

    op.execute(
        """
        UPDATE llm_providers
        SET provider_type = 'dashscope'
        WHERE provider_type = 'qwen'
        """
    )
    op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
    _add_provider_type_constraint_dashscope()


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "llm_providers" not in inspector.get_table_names():
        return

    op.execute(
        """
        UPDATE llm_providers
        SET provider_type = 'qwen'
        WHERE provider_type = 'dashscope'
        """
    )
    op.execute("ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_type")
    _add_provider_type_constraint_qwen()
