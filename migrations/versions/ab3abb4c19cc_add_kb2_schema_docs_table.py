"""Migration: Add kb2_schema_docs table for hybrid schema search index

Revision ID: ab3abb4c19cc
Revises: a7b8c9d0e1f2
Create Date: 2026-10-08 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TSVECTOR
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = 'ab3abb4c19cc'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # 1. Helper function for generated tsvector from title, body, and aliases array
    op.execute("""
        CREATE OR REPLACE FUNCTION kb2_schema_docs_generate_tsv(title text, body text, aliases text[])
        RETURNS tsvector
        LANGUAGE sql
        IMMUTABLE
        RETURN to_tsvector('simple',
            coalesce(title, '') || ' ' ||
            coalesce(body, '') || ' ' ||
            coalesce(array_to_string(aliases, ' '), '')
        );
    """)

    # 2. Table: kb2_schema_docs
    op.create_table(
        'kb2_schema_docs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', UUID(as_uuid=True), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('doc_type', sa.String(length=50), nullable=False),
        sa.Column('item_key', sa.String(length=512), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('aliases', ARRAY(sa.Text()), server_default='{}', nullable=False),
        sa.Column('unit', sa.String(length=100), nullable=True),
        sa.Column('role', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('schema_version', sa.String(length=64), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=True),
        sa.Column(
            'tsv',
            TSVECTOR(),
            sa.Computed("kb2_schema_docs_generate_tsv(title, body, aliases)", persisted=True),
            nullable=True,
        ),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('db_knowledgebase_id', 'doc_type', 'item_key', name='uq_kb2_schema_docs_kb_type_key'),
        sa.CheckConstraint("doc_type IN ('table', 'column', 'metric', 'glossary')", name='ck_kb2_schema_docs_doc_type'),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'rejected', 'conflict', 'stale')", name='ck_kb2_schema_docs_status'),
        sa.CheckConstraint("source IN ('declared', 'inferred', 'llm', 'admin')", name='ck_kb2_schema_docs_source'),
    )

    # 3. Indexes
    op.create_index('ix_kb2_schema_docs_tenant_id', 'kb2_schema_docs', ['tenant_id'])
    op.create_index('ix_kb2_schema_docs_lookup', 'kb2_schema_docs', ['db_knowledgebase_id', 'doc_type', 'status'])
    op.create_index('ix_kb2_schema_docs_tsv', 'kb2_schema_docs', ['tsv'], postgresql_using='gin')
    op.execute("CREATE INDEX ix_kb2_schema_docs_embedding ON kb2_schema_docs USING hnsw (embedding vector_cosine_ops);")

    # 4. Enable Row-Level Security & Create Tenant Isolation Policy
    op.execute("ALTER TABLE kb2_schema_docs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kb2_schema_docs FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS kb2_schema_docs_tenant_isolation ON kb2_schema_docs;")
    op.execute("""
        CREATE POLICY kb2_schema_docs_tenant_isolation ON kb2_schema_docs
        FOR ALL
        USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid))
        WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb2_schema_docs_tenant_isolation ON kb2_schema_docs;")
    op.drop_table('kb2_schema_docs')
    op.execute("DROP FUNCTION IF EXISTS kb2_schema_docs_generate_tsv(text, text, text[]);")
