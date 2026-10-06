"""Phase 2 Knowledge Layer: add pg_trgm and kb2_knowledge_items, kb2_entity_values, kb2_query_memory

Revision ID: b2f3c4d5e6a7
Revises: c09550784c22
Create Date: 2026-10-06 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = 'b2f3c4d5e6a7'
down_revision = 'c09550784c22'
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # 1. Enable pg_trgm extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2. Table: kb2_knowledge_items
    op.create_table(
        'kb2_knowledge_items',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', sa.UUID(), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_type', sa.String(length=50), nullable=False),
        sa.Column('item_key', sa.String(length=512), nullable=False),
        sa.Column('valid_from_version', sa.String(length=64), nullable=False),
        sa.Column('object_hash', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='draft', nullable=False),
        sa.Column('is_locked_by_admin', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_sensitive', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('confidence', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('staged_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reviewed_by', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('db_knowledgebase_id', 'item_type', 'item_key', name='uq_kb2_ki_kb_type_key'),
        sa.CheckConstraint("item_type IN ('table', 'column', 'relationship', 'metric', 'rule', 'example', 'glossary')", name='ck_kb2_ki_item_type'),
        sa.CheckConstraint("source IN ('declared', 'inferred', 'llm', 'admin')", name='ck_kb2_ki_source'),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'rejected', 'conflict', 'stale')", name='ck_kb2_ki_status'),
    )
    op.create_index('ix_kb2_ki_tenant_id', 'kb2_knowledge_items', ['tenant_id'])
    op.create_index('ix_kb2_ki_lookup', 'kb2_knowledge_items', ['db_knowledgebase_id', 'item_type', 'status'])
    op.create_index('ix_kb2_ki_tenant_kb_type', 'kb2_knowledge_items', ['tenant_id', 'db_knowledgebase_id', 'item_type'])

    # 3. Table: kb2_entity_values
    op.create_table(
        'kb2_entity_values',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', sa.UUID(), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('table_name', sa.String(length=255), nullable=False),
        sa.Column('column_name', sa.String(length=255), nullable=False),
        sa.Column('raw_value', sa.Text(), nullable=False),
        sa.Column('normalized_value', sa.Text(), nullable=False),
        sa.Column('frequency_count', sa.Integer(), nullable=True),
        sa.Column('tsv_value', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', raw_value)", persisted=True), nullable=True),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('db_knowledgebase_id', 'table_name', 'column_name', 'normalized_value', name='uq_kb2_entity_val'),
        sa.CheckConstraint('length(normalized_value) <= 255', name='ck_kb2_ev_normalized_value_len'),
    )
    op.create_index('ix_kb2_ev_tenant_id', 'kb2_entity_values', ['tenant_id'])
    op.create_index('ix_kb2_ev_lookup', 'kb2_entity_values', ['db_knowledgebase_id', 'table_name', 'column_name'])
    op.execute("CREATE INDEX ix_kb2_ev_trgm ON kb2_entity_values USING gin (normalized_value gin_trgm_ops);")
    op.create_index('ix_kb2_ev_tsv', 'kb2_entity_values', ['tsv_value'], postgresql_using='gin')

    # 4. Table: kb2_query_memory
    op.create_table(
        'kb2_query_memory',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', sa.UUID(), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_version', sa.String(length=64), nullable=False),
        sa.Column('natural_query', sa.Text(), nullable=False),
        sa.Column('normalized_query', sa.Text(), nullable=False),
        sa.Column('compiled_sql', sa.Text(), nullable=False),
        sa.Column('plan_ir', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('execution_stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.String(length=30), server_default='verified', nullable=False),
        sa.Column('is_locked_by_admin', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('referenced_items', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('db_knowledgebase_id', 'schema_version', 'normalized_query', name='uq_kb2_qm_kb_ver_query'),
        sa.CheckConstraint("status IN ('verified', 'deprecated')", name='ck_kb2_qm_status'),
    )
    op.create_index('ix_kb2_qm_tenant_id', 'kb2_query_memory', ['tenant_id'])
    op.create_index('ix_kb2_qm_lookup', 'kb2_query_memory', ['db_knowledgebase_id', 'schema_version', 'status'])
    op.create_index('ix_kb2_qm_referenced_items', 'kb2_query_memory', ['referenced_items'], postgresql_using='gin')

    # 5. Enable Row-Level Security & Create Tenant Isolation Policies
    tables = ['kb2_knowledge_items', 'kb2_entity_values', 'kb2_query_memory']
    for t in tables:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON {t};")
        op.execute(f"""
            CREATE POLICY {t}_tenant_isolation ON {t}
            FOR ALL
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid))
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid));
        """)


def downgrade() -> None:
    tables = ['kb2_query_memory', 'kb2_entity_values', 'kb2_knowledge_items']
    for t in tables:
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON {t};")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;")

    op.drop_index('ix_kb2_qm_referenced_items', table_name='kb2_query_memory')
    op.drop_index('ix_kb2_qm_lookup', table_name='kb2_query_memory')
    op.drop_index('ix_kb2_qm_tenant_id', table_name='kb2_query_memory')
    op.drop_table('kb2_query_memory')

    op.drop_index('ix_kb2_ev_tsv', table_name='kb2_entity_values')
    op.execute("DROP INDEX IF EXISTS ix_kb2_ev_trgm;")
    op.drop_index('ix_kb2_ev_lookup', table_name='kb2_entity_values')
    op.drop_index('ix_kb2_ev_tenant_id', table_name='kb2_entity_values')
    op.drop_table('kb2_entity_values')

    op.drop_index('ix_kb2_ki_tenant_kb_type', table_name='kb2_knowledge_items')
    op.drop_index('ix_kb2_ki_lookup', table_name='kb2_knowledge_items')
    op.drop_index('ix_kb2_ki_tenant_id', table_name='kb2_knowledge_items')
    op.drop_table('kb2_knowledge_items')
