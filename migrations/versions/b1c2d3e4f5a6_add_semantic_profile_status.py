"""Add semantic_profile_status to db_schema_snapshots and ensure settings in database_knowledgebases

Revision ID: b1c2d3e4f5a6
Revises: ab3abb4c19cc
Create Date: 2026-10-12 14:50:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b1c2d3e4f5a6"
down_revision = "ab3abb4c19cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. db_schema_snapshots.semantic_profile_status
    has_status_col = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='db_schema_snapshots' AND column_name='semantic_profile_status'
    """)).fetchone()

    if not has_status_col:
        op.add_column(
            "db_schema_snapshots",
            sa.Column("semantic_profile_status", sa.String(20), nullable=True),
        )

    # 2. database_knowledgebases.settings
    has_settings_col = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='database_knowledgebases' AND column_name='settings'
    """)).fetchone()

    if not has_settings_col:
        op.add_column(
            "database_knowledgebases",
            sa.Column("settings", JSONB, server_default="{}", nullable=False),
        )


def downgrade() -> None:
    conn = op.get_bind()

    has_status_col = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='db_schema_snapshots' AND column_name='semantic_profile_status'
    """)).fetchone()
    if has_status_col:
        op.drop_column("db_schema_snapshots", "semantic_profile_status")

    has_settings_col = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='database_knowledgebases' AND column_name='settings'
    """)).fetchone()
    if has_settings_col:
        op.drop_column("database_knowledgebases", "settings")
