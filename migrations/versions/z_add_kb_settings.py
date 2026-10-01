from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "z_add_kb_settings"
down_revision = "f6a7fd0e3869"
branch_labels = None
depends_on = None

def upgrade():
    # Make the seed migration idempotent
    conn = op.get_bind()
    has_column = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='database_knowledgebases' AND column_name='settings'
    """)).fetchone()
    
    if not has_column:
        op.add_column("database_knowledgebases", sa.Column("settings", JSONB, server_default='{}', nullable=False))

def downgrade():
    op.drop_column("database_knowledgebases", "settings")
