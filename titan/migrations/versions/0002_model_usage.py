"""gastos com provedores pagos (model_usage)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_brl", sa.Float(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'FINAL', 'FAILED')", name="ck_model_usage_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("model_usage") as batch:
        batch.create_index("ix_model_usage_day", ["day"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("model_usage") as batch:
        batch.drop_index("ix_model_usage_day")
    op.drop_table("model_usage")
