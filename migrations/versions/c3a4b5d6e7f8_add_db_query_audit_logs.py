"""Add db_query_audit_logs table for Phase 3A production observability

Revision ID: c3a4b5d6e7f8
Revises: 58a73d758f42
Create Date: 2026-09-01 17:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c3a4b5d6e7f8'
down_revision = '58a73d758f42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'db_query_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('query_id', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('knowledgebase_id', sa.UUID(), nullable=False),
        sa.Column('schema_version', sa.String(length=64), nullable=True),
        sa.Column('request_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_query_hash', sa.String(length=64), nullable=False),
        sa.Column('user_query_length', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sanitized_user_query', sa.Text(), nullable=False),
        sa.Column('retrieval_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('planning_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('sql_generation_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('validation_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('database_execution_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('result_normalization_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('answer_synthesis_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('grounding_verification_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('total_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('truncated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('column_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('answer_type', sa.String(length=32), server_default='UNKNOWN', nullable=False),
        sa.Column('llm_used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('llm_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('repair_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('ast_valid', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('grounding_status', sa.String(length=32), server_default='UNKNOWN', nullable=False),
        sa.Column('verification_status', sa.String(length=32), server_default='UNKNOWN', nullable=False),
        sa.Column('fallback_used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('error_type', sa.String(length=64), nullable=True),
        sa.Column('sanitized_error', sa.Text(), nullable=True),
        sa.Column('final_status', sa.String(length=32), server_default='SUCCESS', nullable=False),
        sa.Column('audit_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['knowledgebase_id'], ['database_knowledgebases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_db_audit_tenant_id', 'db_query_audit_logs', ['tenant_id'])
    op.create_index('ix_db_audit_query_id', 'db_query_audit_logs', ['query_id'])
    op.create_index('ix_db_audit_kb_id', 'db_query_audit_logs', ['knowledgebase_id'])
    op.create_index('ix_db_audit_tenant_kb', 'db_query_audit_logs', ['tenant_id', 'knowledgebase_id'])
    op.create_index('ix_db_audit_tenant_created', 'db_query_audit_logs', ['tenant_id', 'request_timestamp'])
    op.create_index('ix_db_audit_tenant_status', 'db_query_audit_logs', ['tenant_id', 'final_status'])


def downgrade() -> None:
    op.drop_index('ix_db_audit_tenant_status', table_name='db_query_audit_logs')
    op.drop_index('ix_db_audit_tenant_created', table_name='db_query_audit_logs')
    op.drop_index('ix_db_audit_tenant_kb', table_name='db_query_audit_logs')
    op.drop_index('ix_db_audit_kb_id', table_name='db_query_audit_logs')
    op.drop_index('ix_db_audit_query_id', table_name='db_query_audit_logs')
    op.drop_index('ix_db_audit_tenant_id', table_name='db_query_audit_logs')
    op.drop_table('db_query_audit_logs')
