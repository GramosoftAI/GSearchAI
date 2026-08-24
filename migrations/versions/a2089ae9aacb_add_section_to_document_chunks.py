"""Alembic script template"""
"""Add section to document_chunks

Revision ID: a2089ae9aacb
Revises: de22325e9f67
Create Date: 2026-08-23 13:17:47.464084

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2089ae9aacb'
down_revision = 'de22325e9f67'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('document_chunks', sa.Column('section', sa.String(length=255), nullable=True))
    op.create_index('ix_chunks_kb_section', 'document_chunks', ['kb_id', 'section'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_chunks_kb_section', table_name='document_chunks')
    op.drop_column('document_chunks', 'section')
