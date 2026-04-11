"""add_pgvector_embedding

Revision ID: a1b2c3d4e5f6
Revises: 3efd10f009b0
Create Date: 2026-04-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3efd10f009b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column
    op.add_column("meal_logs", sa.Column("embedding", Vector(768), nullable=True))

    # HNSW index for fast cosine similarity search
    op.create_index(
        "ix_meal_logs_embedding",
        "meal_logs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_meal_logs_embedding", table_name="meal_logs")
    op.drop_column("meal_logs", "embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
