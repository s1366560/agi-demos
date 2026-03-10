"""add_volcengine_provider_type

Revision ID: c4d5e6f7a8b9
Revises: a3c7e5f12b8d
Create Date: 2026-03-10 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "a3c7e5f12b8d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_PROVIDER_TYPES_WITH_VOLCENGINE = (
    "'openai', 'openrouter', 'dashscope', 'gemini', 'anthropic', 'groq', 'azure_openai', "
    "'cohere', 'mistral', 'bedrock', 'vertex', 'deepseek', 'minimax', "
    "'zai', 'kimi', 'volcengine', 'ollama', 'lmstudio', "
    "'dashscope_coding', 'dashscope_embedding', 'dashscope_reranker', "
    "'kimi_coding', 'kimi_embedding', 'kimi_reranker', "
    "'minimax_coding', 'minimax_embedding', 'minimax_reranker', "
    "'zai_coding', 'zai_embedding', 'zai_reranker'"
)

PREVIOUS_PROVIDER_TYPES = (
    "'openai', 'openrouter', 'dashscope', 'gemini', 'anthropic', 'groq', 'azure_openai', "
    "'cohere', 'mistral', 'bedrock', 'vertex', 'deepseek', 'minimax', "
    "'zai', 'kimi', 'ollama', 'lmstudio', "
    "'dashscope_coding', 'dashscope_embedding', 'dashscope_reranker', "
    "'kimi_coding', 'kimi_embedding', 'kimi_reranker', "
    "'minimax_coding', 'minimax_embedding', 'minimax_reranker', "
    "'zai_coding', 'zai_embedding', 'zai_reranker'"
)


def upgrade() -> None:
    """Add volcengine to provider_type CHECK constraint."""
    op.drop_constraint("llm_providers_valid_type", "llm_providers", type_="check")
    op.create_check_constraint(
        "llm_providers_valid_type",
        "llm_providers",
        f"provider_type IN ({ALL_PROVIDER_TYPES_WITH_VOLCENGINE})",
    )


def downgrade() -> None:
    """Remove volcengine from provider_type CHECK constraint."""
    op.drop_constraint("llm_providers_valid_type", "llm_providers", type_="check")
    op.create_check_constraint(
        "llm_providers_valid_type",
        "llm_providers",
        f"provider_type IN ({PREVIOUS_PROVIDER_TYPES})",
    )
