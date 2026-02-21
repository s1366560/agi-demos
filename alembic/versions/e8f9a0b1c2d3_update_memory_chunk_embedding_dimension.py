"""Update memory_chunk embedding dimension to support all models

Revision ID: e8f9a0b1c2d3
Revises: f7b8c9d0e1f2
Create Date: 2026-02-21

Changes:
- Increase embedding vector dimension from 1024 to 3072
- 3072 is the max dimension for text-embedding-3-large
- This allows all common embedding models to be used without migration
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'e8f9a0b1c2d3'
down_revision = 'f7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Increase embedding dimension from 1024 to 3072."""
    # Check if pgvector extension is available
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
    ))
    has_pgvector = result.scalar()

    if not has_pgvector:
        # If pgvector not installed, skip (will use JSON fallback)
        return

    # Drop the existing vector index if exists
    conn.execute(text("DROP INDEX IF EXISTS ix_memory_chunks_embedding"))

    # Alter the column to use larger dimension
    # Note: pgvector allows casting smaller vectors to larger columns
    # Existing 1024-dim vectors will be padded with zeros or need re-embedding
    conn.execute(text("""
        ALTER TABLE memory_chunks
        ALTER COLUMN embedding TYPE vector(3072)
        USING embedding::vector(3072)
    """))

    # Recreate index for the new dimension
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_memory_chunks_embedding
        ON memory_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """))


def downgrade() -> None:
    """Revert embedding dimension to 1024."""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
    ))
    has_pgvector = result.scalar()

    if not has_pgvector:
        return

    # Drop the index
    conn.execute(text("DROP INDEX IF EXISTS ix_memory_chunks_embedding"))

    # Note: Downgrade will fail if any embeddings have > 1024 dimensions
    # This is intentional - data loss prevention
    conn.execute(text("""
        ALTER TABLE memory_chunks
        ALTER COLUMN embedding TYPE vector(1024)
        USING embedding::vector(1024)
    """))

    # Recreate index
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_memory_chunks_embedding
        ON memory_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """))
