"""sócio: memória (cérebro), metas, lembretes/tarefas, mensagens do TITAN

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("important", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("origin", sa.String(length=8), nullable=False, server_default="user"))

    op.create_table(
        "brain_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("message_id", sa.Uuid()),
        sa.Column("question_key", sa.String(32)),
        sa.Column("replaces_id", sa.Uuid()),
        sa.Column("topic", sa.String(16)),
        sa.Column("follow_up_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in("category", ("sobre", "gostos", "negocio", "estudos", "resumo", "outros")),
                           name="ck_brain_category"),
        sa.CheckConstraint(_in("status", ("pending", "active", "archived")), name="ck_brain_status"),
    )
    op.create_index("ix_brain_user_status", "brain_memories", ["user_id", "status"])

    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("current", sa.Float(), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_goals_user", "goals", ["user_id", "done"])

    op.create_table(
        "todos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("message_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in("kind", ("lembrete", "tarefa")), name="ck_todos_kind"),
    )
    op.create_index("ix_todos_user_done", "todos", ["user_id", "done_at"])

    op.create_table(
        "titan_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("todo_id", sa.Uuid()),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in("kind", ("bom_dia", "boa_noite", "papo", "lembrete", "acompanhamento", "socio")),
                           name="ck_notes_kind"),
    )
    op.create_index("ix_notes_user_created", "titan_notes", ["user_id", "created_at"])


def downgrade() -> None:
    for t, ix in (("titan_notes", "ix_notes_user_created"), ("todos", "ix_todos_user_done"),
                  ("goals", "ix_goals_user"), ("brain_memories", "ix_brain_user_status")):
        op.drop_index(ix, table_name=t)
        op.drop_table(t)
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("origin")
        batch.drop_column("important")
