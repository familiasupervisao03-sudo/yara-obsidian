"""TITAN Casa: casas, membros, aparelhos, cenas e registro de comandos

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "casa_homes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_uid", sa.String(64)),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "casa_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("home_id", sa.Uuid(), sa.ForeignKey("casa_homes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("home_id", "user_id", name="uq_casa_member"),
        sa.CheckConstraint(_in("role", ("owner", "member")), name="ck_casa_member_role"),
    )
    op.create_table(
        "casa_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("home_id", sa.Uuid(), sa.ForeignKey("casa_homes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("parent_id", sa.String(80)),
        sa.Column("provider_name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("icon", sa.String(16), nullable=False),
        sa.Column("room", sa.String(40), nullable=False),
        sa.Column("aliases", sa.String(300), nullable=False),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("home_id", "provider", "provider_id", name="uq_casa_device_provider"),
        sa.CheckConstraint(_in("kind", ("plug", "light", "tv", "ac", "fan", "other")), name="ck_casa_device_kind"),
    )
    op.create_index("ix_casa_devices_home", "casa_devices", ["home_id"])
    op.create_table(
        "casa_scenes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("home_id", sa.Uuid(), sa.ForeignKey("casa_homes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("phrases", sa.String(300), nullable=False),
        sa.Column("reply", sa.String(300), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_casa_scenes_home", "casa_scenes", ["home_id"])
    op.create_table(
        "casa_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("home_id", sa.Uuid(), sa.ForeignKey("casa_homes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("device_id", sa.Uuid()),
        sa.Column("scene_id", sa.Uuid()),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_casa_events_home_created", "casa_events", ["home_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_casa_events_home_created", table_name="casa_events")
    op.drop_table("casa_events")
    op.drop_index("ix_casa_scenes_home", table_name="casa_scenes")
    op.drop_table("casa_scenes")
    op.drop_index("ix_casa_devices_home", table_name="casa_devices")
    op.drop_table("casa_devices")
    op.drop_table("casa_members")
    op.drop_table("casa_homes")
