"""Mensagens do TITAN entregues por aparelho (celular e notebook recebem cada um a sua cópia).

Revision ID: 0007
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("titan_notes") as b:
        b.add_column(sa.Column("delivered_to", sa.String(400), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("titan_notes") as b:
        b.drop_column("delivered_to")
