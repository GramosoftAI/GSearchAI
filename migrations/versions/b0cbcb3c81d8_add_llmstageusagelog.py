"""Add LLMStageUsageLog

Revision ID: b0cbcb3c81d8
Revises: e32c19c5a944
Create Date: 2026-08-27 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0cbcb3c81d8'
down_revision: Union[str, None] = 'e32c19c5a944'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('llm_stage_usage_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('task_type', sa.String(length=100), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('query_preview', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_stage_usage_logs_created_at'), 'llm_stage_usage_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_llm_stage_usage_logs_id'), 'llm_stage_usage_logs', ['id'], unique=False)
    op.create_index(op.f('ix_llm_stage_usage_logs_model_name'), 'llm_stage_usage_logs', ['model_name'], unique=False)
    op.create_index(op.f('ix_llm_stage_usage_logs_task_type'), 'llm_stage_usage_logs', ['task_type'], unique=False)
    op.create_index(op.f('ix_llm_stage_usage_logs_tenant_id'), 'llm_stage_usage_logs', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_llm_stage_usage_logs_tenant_id'), table_name='llm_stage_usage_logs')
    op.drop_index(op.f('ix_llm_stage_usage_logs_task_type'), table_name='llm_stage_usage_logs')
    op.drop_index(op.f('ix_llm_stage_usage_logs_model_name'), table_name='llm_stage_usage_logs')
    op.drop_index(op.f('ix_llm_stage_usage_logs_id'), table_name='llm_stage_usage_logs')
    op.drop_index(op.f('ix_llm_stage_usage_logs_created_at'), table_name='llm_stage_usage_logs')
    op.drop_table('llm_stage_usage_logs')
