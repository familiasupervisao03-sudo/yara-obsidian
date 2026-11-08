"""mensagens: estado (completa/interrompida) e ponto de interrupção

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=False,
                                   server_default="complete"))
        batch.add_column(sa.Column("interrupted_at_char", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("interrupted_at_char")
        batch.drop_column("status")
