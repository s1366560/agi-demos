"""add_memory_chunks_with_pgvector

Revision ID: d8f2a1c3e5b7
Revises: c7a3e5f1b2d4
Create Date: 2026-02-18 05:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f2a1c3e5b7"
down_revision: Union[str, None] = "c7a3e5f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create memory_chunks table
    op.create_table(
        "memory_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}"),
        sa.Column("importance", sa.Float(), server_default="0.5"),
        sa.Column("category", sa.String(20), server_default="'other'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add vector column via raw SQL (pgvector type not in SQLAlchemy Column)
    op.execute(
        "ALTER TABLE memory_chunks ADD COLUMN embedding vector(1024)"
    )

    # Create indexes
    op.create_index(
        "ix_chunks_project_source",
        "memory_chunks",
        ["project_id", "source_type"],
    )
    op.create_index(
        "ix_chunks_content_hash",
        "memory_chunks",
        ["content_hash"],
    )

    # GIN index for full-text search on content
    op.execute("""
        CREATE INDEX ix_chunks_content_fts
        ON memory_chunks
        USING gin(to_tsvector('simple', content))
    """)

    # IVFFlat index for vector similarity search
    # Note: IVFFlat requires some data to build properly;
    # for empty tables, use HNSW instead
    op.execute("""
        CREATE INDEX ix_chunks_embedding_hnsw
        ON memory_chunks
        USING hnsw(embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.drop_table("memory_chunks")
    # Note: we don't drop the vector extension as other tables may use it
