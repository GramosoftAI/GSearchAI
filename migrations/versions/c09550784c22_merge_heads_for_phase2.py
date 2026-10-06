"""Alembic script template"""
"""merge_heads_for_phase2

Revision ID: c09550784c22
Revises: 8bd885283dbe, z_add_kb_settings
Create Date: 2026-10-06 11:22:49.149416

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c09550784c22'
down_revision = ('8bd885283dbe', 'z_add_kb_settings')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
