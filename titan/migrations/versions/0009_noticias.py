"""Notícias do TITAN: notícias lidas dos sites, agrupadas por fato, o que cada conta fez nelas,
assuntos seguidos (com o que foi achado de verdade), dicionário e fontes de cada conta.

Revision ID: 0009
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

OLD_KINDS = ("bom_dia", "boa_noite", "papo", "lembrete", "acompanhamento", "socio")
NEW_KINDS = OLD_KINDS + ("noticia", "jornal")


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "news_stories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("words", sa.String(600), nullable=False, server_default=""),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_checagem", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_stories_last", "news_stories", ["last_at"])
    op.create_table(
        "news_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("url", sa.String(1000), nullable=False, unique=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("story_id", sa.Uuid(), sa.ForeignKey("news_stories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_items_published", "news_items", ["published_at"])
    op.create_index("ix_news_items_story", "news_items", ["story_id"])
    op.create_table(
        "news_user_stories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("story_id", sa.Uuid(), sa.ForeignKey("news_stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("saved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vote", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("analysis", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "story_id", name="uq_news_user_story"),
    )
    op.create_index("ix_news_user_story_user", "news_user_stories", ["user_id", "updated_at"])
    op.create_table(
        "news_follows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("prices", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("store_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_follows_user", "news_follows", ["user_id"])
    op.create_table(
        "news_follow_hits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("follow_id", sa.Uuid(), sa.ForeignKey("news_follows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float()),
        sa.Column("quote", sa.String(400), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("follow_id", "url", name="uq_news_follow_hit"),
    )
    op.create_index("ix_news_follow_hits_follow", "news_follow_hits", ["follow_id", "published_at"])
    op.create_table(
        "news_terms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.String(80), nullable=False),
        sa.Column("explanation", sa.String(600), nullable=False),
        sa.Column("story_id", sa.Uuid(), sa.ForeignKey("news_stories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "term", name="uq_news_term"),
    )
    op.create_table(
        "news_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("category", sa.String(20), nullable=False, server_default="tecnologia"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "url", name="uq_news_source"),
    )
    # Mensagens do TITAN agora também podem ser "noticia" (importante) e "jornal" (resumo do dia).
    with op.batch_alter_table("titan_notes", recreate="always") as b:
        b.drop_constraint("ck_notes_kind", type_="check")
        b.create_check_constraint("ck_notes_kind", _in("kind", NEW_KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM titan_notes WHERE kind IN ('noticia', 'jornal')")
    with op.batch_alter_table("titan_notes", recreate="always") as b:
        b.drop_constraint("ck_notes_kind", type_="check")
        b.create_check_constraint("ck_notes_kind", _in("kind", OLD_KINDS))
    for t in ("news_sources", "news_terms", "news_follow_hits", "news_follows", "news_user_stories",
              "news_items", "news_stories"):
        op.drop_table(t)
