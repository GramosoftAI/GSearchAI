"""Add categorical_values to knowledge_bases

Revision ID: 9f1234abcd56
Revises: f6a7fd0e3869
Create Date: 2026-08-26 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9f1234abcd56'
down_revision = 'f6a7fd0e3869'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # We add categorical_values to knowledge_bases table
    op.add_column('knowledge_bases', sa.Column('categorical_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

def downgrade() -> None:
    op.drop_column('knowledge_bases', 'categorical_values')
