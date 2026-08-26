"""Create the Milestone 0 metadata schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


metric_provenance = postgresql.ENUM(
    "observed",
    "estimated",
    "owner_verified",
    name="metric_provenance",
    create_type=False,
)
crawl_run_status = postgresql.ENUM(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="crawl_run_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    metric_provenance.create(bind, checkfirst=True)
    crawl_run_status.create(bind, checkfirst=True)

    op.create_table(
        "boorus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("adapter_family", sa.String(length=50), nullable=False),
        sa.Column("adapter_name", sa.String(length=100), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_boorus"),
        sa.UniqueConstraint("canonical_url", name="uq_boorus_canonical_url"),
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booru_id", sa.Uuid(), nullable=False),
        sa.Column("adapter_name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            crawl_run_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_crawl_runs_finished_not_before_started"),
        ),
        sa.ForeignKeyConstraint(
            ["booru_id"],
            ["boorus.id"],
            name="fk_crawl_runs_booru_id_boorus",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_runs"),
    )
    op.create_index(
        "ix_crawl_runs_booru_started_at",
        "crawl_runs",
        ["booru_id", "started_at"],
    )

    op.create_table(
        "booru_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booru_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("health_status", sa.String(length=50), nullable=True),
        sa.Column("health_provenance", metric_provenance, nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("capabilities_provenance", metric_provenance, nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(health_status IS NULL) = (health_provenance IS NULL)",
            name=op.f("ck_booru_snapshots_health_provenance_pair"),
        ),
        sa.CheckConstraint(
            "(capabilities IS NULL) = (capabilities_provenance IS NULL)",
            name=op.f("ck_booru_snapshots_capabilities_provenance_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["booru_id"],
            ["boorus.id"],
            name="fk_booru_snapshots_booru_id_boorus",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"],
            ["crawl_runs.id"],
            name="fk_booru_snapshots_crawl_run_id_crawl_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_booru_snapshots"),
        sa.UniqueConstraint(
            "booru_id",
            "crawl_run_id",
            name="uq_booru_snapshots_booru_id",
        ),
    )
    op.create_index(
        "ix_booru_snapshots_booru_captured_at",
        "booru_snapshots",
        ["booru_id", "captured_at"],
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booru_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["booru_id"],
            ["boorus.id"],
            name="fk_tags_booru_id_boorus",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("booru_id", "name", name="uq_tags_booru_id"),
    )
    op.create_index("ix_tags_booru_last_seen_at", "tags", ["booru_id", "last_seen_at"])

    op.create_table(
        "tag_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("post_count", sa.BigInteger(), nullable=False),
        sa.Column("post_count_provenance", metric_provenance, nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"],
            ["crawl_runs.id"],
            name="fk_tag_snapshots_crawl_run_id_crawl_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name="fk_tag_snapshots_tag_id_tags",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tag_snapshots"),
        sa.UniqueConstraint("tag_id", "crawl_run_id", name="uq_tag_snapshots_tag_id"),
    )
    op.create_index(
        "ix_tag_snapshots_tag_captured_at",
        "tag_snapshots",
        ["tag_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tag_snapshots_tag_captured_at", table_name="tag_snapshots")
    op.drop_table("tag_snapshots")
    op.drop_index("ix_tags_booru_last_seen_at", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_booru_snapshots_booru_captured_at", table_name="booru_snapshots")
    op.drop_table("booru_snapshots")
    op.drop_index("ix_crawl_runs_booru_started_at", table_name="crawl_runs")
    op.drop_table("crawl_runs")
    op.drop_table("boorus")

    bind = op.get_bind()
    crawl_run_status.drop(bind, checkfirst=True)
    metric_provenance.drop(bind, checkfirst=True)
