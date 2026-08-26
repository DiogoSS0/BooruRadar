from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from booruradar.models.base import Base


if TYPE_CHECKING:
    from booruradar.models.crawl_run import CrawlRun
    from booruradar.models.snapshot import BooruSnapshot
    from booruradar.models.tag import Tag


class Booru(Base):
    __tablename__ = "boorus"
    __table_args__ = (UniqueConstraint("canonical_url"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    canonical_url: Mapped[str] = mapped_column(Text)
    adapter_family: Mapped[str] = mapped_column(String(50))
    adapter_name: Mapped[str | None] = mapped_column(String(100))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    crawl_runs: Mapped[list[CrawlRun]] = relationship(back_populates="booru")
    snapshots: Mapped[list[BooruSnapshot]] = relationship(back_populates="booru")
    tags: Mapped[list[Tag]] = relationship(back_populates="booru")
