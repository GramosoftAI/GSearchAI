"""Migration: Add kb2_audit_log table with RLS

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-06 17:17:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kb2_audit_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', UUID(as_uuid=True), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('item_key', sa.String(512), nullable=False),
        sa.Column('before', JSONB, nullable=True),
        sa.Column('after', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    op.create_index('ix_kb2_audit_tenant_id', 'kb2_audit_log', ['tenant_id'])
    op.create_index('ix_kb2_audit_lookup', 'kb2_audit_log', ['db_knowledgebase_id', 'item_key'])
    op.create_index('ix_kb2_audit_created', 'kb2_audit_log', ['created_at'])

    # Enable RLS
    op.execute("ALTER TABLE kb2_audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY rls_kb2_audit_log_tenant ON kb2_audit_log
        AS PERMISSIVE
        FOR ALL
        TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS rls_kb2_audit_log_tenant ON kb2_audit_log;")
    op.drop_table('kb2_audit_log')
