"""Allow succeeded_with_warnings in kb2_job_runs status check constraint

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-10-14 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_kb2_job_runs_status", "kb2_job_runs", type_="check")
    op.create_check_constraint(
        "ck_kb2_job_runs_status",
        "kb2_job_runs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded', 'succeeded_with_warnings')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_kb2_job_runs_status", "kb2_job_runs", type_="check")
    op.create_check_constraint(
        "ck_kb2_job_runs_status",
        "kb2_job_runs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
    )
