"""Alembic script template"""
"""fix_hnsw_index

Revision ID: d2752ca06b8c
Revises: 2aec6bb7d18d
Create Date: 2026-09-23 11:53:25.635188

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2752ca06b8c'
down_revision = '2aec6bb7d18d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old unused column
    op.drop_column('document_chunks', 'embedding')
    
    # We must use AUTOCOMMIT for CONCURRENTLY
    with op.get_context().autocommit_block():
        # Drop test indexes if they exist
        op.execute("DROP INDEX IF EXISTS test_hnsw_check;")
        op.execute("DROP INDEX IF EXISTS test_hnsw_check2;")
        
        # Drop the old ivfflat index
        op.execute("DROP INDEX IF EXISTS idx_doc_chunks_bge;")
        
        # Create the new HNSW index CONCURRENTLY
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_embedding_bge_hnsw ON document_chunks USING hnsw (embedding_bge vector_cosine_ops) WITH (m = 32, ef_construction = 128);")


def downgrade() -> None:
    # Re-add the dead column
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);")
    
    with op.get_context().autocommit_block():
        # Drop the HNSW index
        op.execute("DROP INDEX IF EXISTS idx_chunks_embedding_bge_hnsw;")
        
        # Recreate the old ivfflat index exactly as it was
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_doc_chunks_bge ON document_chunks USING ivfflat (embedding_bge vector_cosine_ops) WITH (lists='100');")
