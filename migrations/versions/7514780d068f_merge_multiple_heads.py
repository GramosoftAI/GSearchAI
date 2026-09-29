"""Alembic script template"""
"""merge multiple heads

Revision ID: 7514780d068f
Revises: bb2d6133a39e, e7f8a9b0c1d2
Create Date: 2026-09-28 11:15:16.540549

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7514780d068f'
down_revision = ('bb2d6133a39e', 'e7f8a9b0c1d2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
