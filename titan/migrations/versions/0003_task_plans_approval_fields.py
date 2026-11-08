"""fase 2: versões de plano e campos de aprovação (risco, validade)

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version", name="uq_task_plans_version"),
    )
    with op.batch_alter_table("approvals") as batch:
        batch.add_column(sa.Column("risk", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.drop_column("expires_at")
        batch.drop_column("risk")
    op.drop_table("task_plans")
