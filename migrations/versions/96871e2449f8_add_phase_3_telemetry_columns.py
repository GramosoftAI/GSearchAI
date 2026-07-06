from alembic import op
import sqlalchemy as sa

revision = '96871e2449f8'
down_revision = '1e5eddefd2df'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('document_ingestion_runs', sa.Column('graph_cleanup_time_ms', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_ingestion_runs', sa.Column('candidate_lookup_time_ms', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_ingestion_runs', sa.Column('llm_review_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_ingestion_runs', sa.Column('auto_merge_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_ingestion_runs', sa.Column('ignored_candidate_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('document_ingestion_runs', sa.Column('cross_document_candidate_count', sa.Integer(), nullable=False, server_default='0'))

def downgrade() -> None:
    pass
