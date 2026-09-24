"""Alembic script template"""
"""merge_all_heads

Revision ID: 904080d47b23
Revises: d4e5f6a7b8c9, c2e45f910a12
Create Date: 2026-09-16 00:46:20.675232

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '904080d47b23'
down_revision = ('d4e5f6a7b8c9', 'c2e45f910a12')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
