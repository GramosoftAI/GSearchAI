from alembic import op
import sqlalchemy as sa

revision = 'a123b456c789'
down_revision = '96871e2449f8'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('document_ingestion_runs', sa.Column('cleanup_timeout_triggered', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('document_ingestion_runs', sa.Column('cleanup_fallback_mode', sa.Boolean(), nullable=False, server_default='false'))

def downgrade() -> None:
    op.drop_column('document_ingestion_runs', 'cleanup_timeout_triggered')
    op.drop_column('document_ingestion_runs', 'cleanup_fallback_mode')
