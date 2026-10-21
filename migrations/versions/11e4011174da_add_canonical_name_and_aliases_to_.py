"""Alembic script template"""
"""add_canonical_name_and_aliases_to_knowledge_bases

Revision ID: 11e4011174da
Revises: c1d2e3f4a5b6
Create Date: 2026-10-21 17:11:18.832624

"""
from alembic import op
import sqlalchemy as sa


from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '11e4011174da'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('knowledge_bases', sa.Column('canonical_name', sa.String(length=255), nullable=True))
    op.add_column('knowledge_bases', sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True))


def downgrade() -> None:
    op.drop_column('knowledge_bases', 'aliases')
    op.drop_column('knowledge_bases', 'canonical_name')

