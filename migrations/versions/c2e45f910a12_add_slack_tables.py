"""Add Slack integration tables

Revision ID: c2e45f910a12
Revises: 58a73d758f42, b0cbcb3c81d8
Create Date: 2026-09-09 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2e45f910a12'
down_revision: Union[str, Sequence[str], None] = ('58a73d758f42', 'b0cbcb3c81d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. slack_connections
    op.create_table(
        'slack_connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('slack_team_id', sa.String(length=64), nullable=False),
        sa.Column('slack_team_name', sa.String(length=255), nullable=True),
        sa.Column('slack_channel_id', sa.String(length=64), nullable=True),
        sa.Column('slack_channel_name', sa.String(length=255), nullable=True),
        sa.Column('bot_user_id', sa.String(length=64), nullable=True),
        sa.Column('bot_access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('scopes', sa.Text(), nullable=True),
        sa.Column('installed_by_user_id', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_slack_connections_id'), 'slack_connections', ['id'], unique=False)
    op.create_index(op.f('ix_slack_connections_tenant_id'), 'slack_connections', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_slack_connections_agent_id'), 'slack_connections', ['agent_id'], unique=False)
    op.create_index(op.f('ix_slack_connections_slack_team_id'), 'slack_connections', ['slack_team_id'], unique=False)
    op.create_index(op.f('ix_slack_connections_slack_channel_id'), 'slack_connections', ['slack_channel_id'], unique=False)
    op.create_index(op.f('ix_slack_connections_is_active'), 'slack_connections', ['is_active'], unique=False)
    op.create_index(op.f('ix_slack_connections_created_at'), 'slack_connections', ['created_at'], unique=False)
    op.create_index('ix_slack_connections_tenant_agent', 'slack_connections', ['tenant_id', 'agent_id'], unique=False)
    op.create_index(
        'uq_slack_team_channel_active',
        'slack_connections',
        ['slack_team_id', 'slack_channel_id'],
        unique=True,
        postgresql_where=sa.text("is_active = true AND slack_channel_id IS NOT NULL")
    )

    # 2. slack_events
    op.create_table(
        'slack_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('event_id', sa.String(length=128), nullable=False),
        sa.Column('slack_team_id', sa.String(length=64), nullable=False),
        sa.Column('channel_id', sa.String(length=64), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id')
    )
    op.create_index(op.f('ix_slack_events_id'), 'slack_events', ['id'], unique=False)
    op.create_index(op.f('ix_slack_events_tenant_id'), 'slack_events', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_slack_events_event_id'), 'slack_events', ['event_id'], unique=True)
    op.create_index(op.f('ix_slack_events_slack_team_id'), 'slack_events', ['slack_team_id'], unique=False)
    op.create_index(op.f('ix_slack_events_channel_id'), 'slack_events', ['channel_id'], unique=False)
    op.create_index(op.f('ix_slack_events_created_at'), 'slack_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('slack_events')
    op.drop_table('slack_connections')
