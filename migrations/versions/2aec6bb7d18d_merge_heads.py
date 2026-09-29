"""Alembic script template"""
"""merge_heads

Revision ID: 2aec6bb7d18d
Revises: bb2d6133a39e, e7f8a9b0c1d2
Create Date: 2026-09-23 11:53:19.499286

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2aec6bb7d18d'
down_revision = ('bb2d6133a39e', 'e7f8a9b0c1d2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
