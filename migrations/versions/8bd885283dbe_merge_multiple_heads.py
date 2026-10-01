"""Alembic script template"""
"""merge multiple heads

Revision ID: 8bd885283dbe
Revises: 7514780d068f, d2752ca06b8c
Create Date: 2026-09-30 16:57:01.203653

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8bd885283dbe'
down_revision = ('7514780d068f', 'd2752ca06b8c')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
