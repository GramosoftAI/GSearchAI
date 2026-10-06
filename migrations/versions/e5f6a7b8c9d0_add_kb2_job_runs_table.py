"""Migration: Add kb2_job_runs table for Phase 2 pipeline execution tracking

Tracks pipeline runs per tenant, KB, and schema version with stage metrics,
lifecycle statuses (queued, running, succeeded, failed, superseded),
and heartbeat tracking for stale run recovery. Protected by RLS.

Revision ID: e5f6a7b8c9d0
Revises: c3f4d5e6a7b8
Create Date: 2026-10-06 14:05:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'c3f4d5e6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create kb2_job_runs table
    op.create_table(
        'kb2_job_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('db_knowledgebase_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('database_knowledgebases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_version', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), server_default='queued', nullable=False),
        sa.Column('stages', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name='ck_kb2_job_runs_status',
        ),
    )

    # 2. Indexes
    op.create_index('ix_kb2_job_runs_tenant_id', 'kb2_job_runs', ['tenant_id'])
    op.create_index('ix_kb2_job_runs_lookup', 'kb2_job_runs', ['db_knowledgebase_id', 'schema_version', 'status'])
    op.create_index('ix_kb2_job_runs_heartbeat', 'kb2_job_runs', ['status', 'heartbeat_at'])

    # 3. Enable RLS and Tenant Isolation Policy
    op.execute("ALTER TABLE kb2_job_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY kb2_job_runs_tenant_isolation ON kb2_job_runs
        FOR ALL
        USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid))
        WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant', true), '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb2_job_runs_tenant_isolation ON kb2_job_runs;")
    op.execute("ALTER TABLE kb2_job_runs DISABLE ROW LEVEL SECURITY;")
    op.drop_index('ix_kb2_job_runs_heartbeat', table_name='kb2_job_runs')
    op.drop_index('ix_kb2_job_runs_lookup', table_name='kb2_job_runs')
    op.drop_index('ix_kb2_job_runs_tenant_id', table_name='kb2_job_runs')
    op.drop_table('kb2_job_runs')
