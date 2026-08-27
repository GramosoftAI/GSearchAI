"""Alembic script template"""
"""empty message

Revision ID: 58a73d758f42
Revises: 9f1234abcd56, a816e735db90, e32c19c5a944
Create Date: 2026-08-26 10:34:36.406389

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '58a73d758f42'
down_revision = ('9f1234abcd56', 'a816e735db90', 'e32c19c5a944')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
