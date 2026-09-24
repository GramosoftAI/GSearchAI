"""Alembic script template"""
"""merge multiple heads

Revision ID: bb2d6133a39e
Revises: c2e45f910a12, d4e5f6a7b8c9
Create Date: 2026-09-19 22:25:04.977460

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bb2d6133a39e'
down_revision = ('c2e45f910a12', 'd4e5f6a7b8c9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
