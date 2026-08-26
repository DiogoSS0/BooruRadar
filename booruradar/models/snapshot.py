from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from booruradar.core.enums import MetricProvenance
from booruradar.models.base import Base, metric_provenance_enum


if TYPE_CHECKING:
    from booruradar.models.booru import Booru
    from booruradar.models.crawl_run import CrawlRun


class BooruSnapshot(Base):
    __tablename__ = "booru_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(health_status IS NULL) = (health_provenance IS NULL)",
            name="health_provenance_pair",
        ),
        CheckConstraint(
            "(capabilities IS NULL) = (capabilities_provenance IS NULL)",
            name="capabilities_provenance_pair",
        ),
        UniqueConstraint("booru_id", "crawl_run_id"),
        Index("ix_booru_snapshots_booru_captured_at", "booru_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booru_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boorus.id", ondelete="CASCADE"),
    )
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_runs.id", ondelete="CASCADE"),
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    health_status: Mapped[str | None] = mapped_column(String(50))
    health_provenance: Mapped[MetricProvenance | None] = mapped_column(metric_provenance_enum)
    capabilities: Mapped[list[str] | None] = mapped_column(JSONB)
    capabilities_provenance: Mapped[MetricProvenance | None] = mapped_column(
        metric_provenance_enum,
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    source_url: Mapped[str | None] = mapped_column(Text)

    booru: Mapped[Booru] = relationship(back_populates="snapshots")
    crawl_run: Mapped[CrawlRun] = relationship(back_populates="booru_snapshots")
