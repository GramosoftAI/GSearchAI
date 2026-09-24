

"""add_bge_embeddings

Revision ID: e7f8a9b0c1d2
Revises: 904080d47b23
Create Date: 2026-09-17 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = 'e7f8a9b0c1d2'
down_revision = '904080d47b23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the missing 1024-dim BGE vector columns
    op.execute("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS summary_embedding_bge vector(1024);")
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_bge vector(1024);")


def downgrade() -> None:
    op.drop_column('document_chunks', 'embedding_bge')
    op.drop_column('knowledge_bases', 'summary_embedding_bge')
