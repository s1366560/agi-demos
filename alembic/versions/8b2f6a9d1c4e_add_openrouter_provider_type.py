"""add_openrouter_provider_type

Revision ID: 8b2f6a9d1c4e
Revises: 0078f966ce4b
Create Date: 2026-03-08 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b2f6a9d1c4e"
down_revision: str | Sequence[str] | None = "0078f966ce4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_PROVIDER_TYPES_WITH_OPENROUTER = (
    "'openai', 'openrouter', 'dashscope', 'gemini', 'anthropic', 'groq', 'azure_openai', "
    "'cohere', 'mistral', 'bedrock', 'vertex', 'deepseek', 'minimax', "
    "'zai', 'kimi', 'ollama', 'lmstudio', "
    "'dashscope_coding', 'dashscope_embedding', 'dashscope_reranker', "
    "'kimi_coding', 'kimi_embedding', 'kimi_reranker', "
    "'minimax_coding', 'minimax_embedding', 'minimax_reranker', "
    "'zai_coding', 'zai_embedding', 'zai_reranker'"
)

PREVIOUS_PROVIDER_TYPES = (
    "'openai', 'dashscope', 'gemini', 'anthropic', 'groq', 'azure_openai', "
    "'cohere', 'mistral', 'bedrock', 'vertex', 'deepseek', 'minimax', "
    "'zai', 'kimi', 'ollama', 'lmstudio', "
    "'dashscope_coding', 'dashscope_embedding', 'dashscope_reranker', "
    "'kimi_coding', 'kimi_embedding', 'kimi_reranker', "
    "'minimax_coding', 'minimax_embedding', 'minimax_reranker', "
    "'zai_coding', 'zai_embedding', 'zai_reranker'"
)


def upgrade() -> None:
    """Add openrouter to provider_type CHECK constraint."""
    op.drop_constraint("llm_providers_valid_type", "llm_providers", type_="check")
    op.create_check_constraint(
        "llm_providers_valid_type",
        "llm_providers",
        f"provider_type IN ({ALL_PROVIDER_TYPES_WITH_OPENROUTER})",
    )


def downgrade() -> None:
    """Remove openrouter from provider_type CHECK constraint."""
    op.drop_constraint("llm_providers_valid_type", "llm_providers", type_="check")
    op.create_check_constraint(
        "llm_providers_valid_type",
        "llm_providers",
        f"provider_type IN ({PREVIOUS_PROVIDER_TYPES})",
    )
