from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from booruradar.core.enums import MetricProvenance
from booruradar.models.base import Base, metric_provenance_enum


if TYPE_CHECKING:
    from booruradar.models.booru import Booru
    from booruradar.models.crawl_run import CrawlRun


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("booru_id", "name"),
        Index("ix_tags_booru_last_seen_at", "booru_id", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booru_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boorus.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booru: Mapped[Booru] = relationship(back_populates="tags")
    snapshots: Mapped[list[TagSnapshot]] = relationship(back_populates="tag")


class TagSnapshot(Base):
    __tablename__ = "tag_snapshots"
    __table_args__ = (
        UniqueConstraint("tag_id", "crawl_run_id"),
        Index("ix_tag_snapshots_tag_captured_at", "tag_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
    )
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="CASCADE"),
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    post_count: Mapped[int] = mapped_column(BigInteger)
    post_count_provenance: Mapped[MetricProvenance] = mapped_column(metric_provenance_enum)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    tag: Mapped[Tag] = relationship(back_populates="snapshots")
    crawl_run: Mapped[CrawlRun] = relationship(back_populates="tag_snapshots")
