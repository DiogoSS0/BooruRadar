from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from booruradar.core.enums import CrawlRunStatus
from booruradar.models.base import Base, crawl_run_status_enum


if TYPE_CHECKING:
    from booruradar.models.booru import Booru
    from booruradar.models.snapshot import BooruSnapshot
    from booruradar.models.tag import TagSnapshot


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_not_before_started",
        ),
        Index("ix_crawl_runs_booru_started_at", "booru_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booru_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boorus.id", ondelete="CASCADE"),
    )
    adapter_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[CrawlRunStatus] = mapped_column(
        crawl_run_status_enum,
        default=CrawlRunStatus.PENDING,
        server_default=CrawlRunStatus.PENDING.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    booru: Mapped[Booru] = relationship(back_populates="crawl_runs")
    booru_snapshots: Mapped[list[BooruSnapshot]] = relationship(back_populates="crawl_run")
    tag_snapshots: Mapped[list[TagSnapshot]] = relationship(back_populates="crawl_run")
