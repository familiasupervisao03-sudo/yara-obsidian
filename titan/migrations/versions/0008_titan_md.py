"""TITAN.md: o manual de como o TITAN age com cada dono (versões) e as sugestões do TITAN.

Revision ID: 0008
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "titan_md_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_titan_md_user_created", "titan_md_versions", ["user_id", "created_at"])
    op.create_table(
        "titan_md_suggestions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line", sa.String(300), nullable=False),
        sa.Column("section", sa.String(60), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_titan_md_sugg_user_status", "titan_md_suggestions", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_titan_md_sugg_user_status", "titan_md_suggestions")
    op.drop_table("titan_md_suggestions")
    op.drop_index("ix_titan_md_user_created", "titan_md_versions")
    op.drop_table("titan_md_versions")
