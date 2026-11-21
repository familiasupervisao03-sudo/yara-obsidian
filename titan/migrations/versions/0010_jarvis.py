"""Funções do Jarvis: mensagens de clima ("vai chover") e da casa (chegada, saída, protocolos).

Revision ID: 0010
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

OLD_KINDS = ("bom_dia", "boa_noite", "papo", "lembrete", "acompanhamento", "socio", "noticia", "jornal", "sistema")
NEW_KINDS = OLD_KINDS + ("clima", "casa")


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    with op.batch_alter_table("titan_notes", recreate="always") as b:
        b.drop_constraint("ck_notes_kind", type_="check")
        b.create_check_constraint("ck_notes_kind", _in("kind", NEW_KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM titan_notes WHERE kind IN ('clima', 'casa')")
    with op.batch_alter_table("titan_notes", recreate="always") as b:
        b.drop_constraint("ck_notes_kind", type_="check")
        b.create_check_constraint("ck_notes_kind", _in("kind", OLD_KINDS))
