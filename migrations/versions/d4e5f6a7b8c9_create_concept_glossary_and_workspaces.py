"""Create concept_glossary and schema_workspace tables

Revision ID: d4e5f6a7b8c9
Revises: c3a4b5d6e7f8
Create Date: 2026-09-07 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3a4b5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create concept_glossary table
    op.create_table(
        'concept_glossary',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('table_name', sa.String(length=255), nullable=False),
        sa.Column('column_name', sa.String(length=255), nullable=False),
        sa.Column('business_description', sa.Text(), nullable=False),
        sa.Column('synonyms', postgresql.ARRAY(sa.String()), server_default='{}', nullable=False),
        sa.Column('semantic_role', sa.String(length=100), nullable=False),
        sa.Column('is_canonical', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('confidence_source', sa.String(length=50), nullable=False),
        sa.Column('schema_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('orphaned_by_drift', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'table_name', 'column_name', 'schema_fingerprint', name='uq_concept_glossary_item'),
        sa.CheckConstraint("confidence_source IN ('LLM_GENERATED','HUMAN_VERIFIED')", name='ck_concept_glossary_source'),
    )

    op.create_index(
        'idx_concept_glossary_role',
        'concept_glossary',
        ['tenant_id', 'semantic_role'],
        unique=False,
        postgresql_where=sa.text('is_canonical = true'),
    )

    op.create_index(
        'idx_concept_glossary_synonyms',
        'concept_glossary',
        ['synonyms'],
        unique=False,
        postgresql_using='gin',
    )

    op.create_index(
        'idx_concept_glossary_tenant_fp',
        'concept_glossary',
        ['tenant_id', 'schema_fingerprint'],
        unique=False,
    )

    # 2. Create schema_workspace table
    op.create_table(
        'schema_workspace',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('workspace_name', sa.String(length=100), nullable=False),
        sa.Column('table_name', sa.String(length=255), nullable=False),
        sa.Column('schema_fingerprint', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'table_name', 'schema_fingerprint', name='uq_schema_workspace_item'),
    )

    op.create_index(
        'ix_schema_workspace_tenant_ws',
        'schema_workspace',
        ['tenant_id', 'workspace_name'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_schema_workspace_tenant_ws', table_name='schema_workspace')
    op.drop_table('schema_workspace')

    op.drop_index('idx_concept_glossary_tenant_fp', table_name='concept_glossary')
    op.drop_index('idx_concept_glossary_synonyms', table_name='concept_glossary')
    op.drop_index('idx_concept_glossary_role', table_name='concept_glossary')
    op.drop_table('concept_glossary')
