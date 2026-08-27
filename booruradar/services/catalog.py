from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from booruradar.core.enums import MetricProvenance
from booruradar.models.booru import Booru
from booruradar.models.snapshot import BooruSnapshot
from booruradar.services.analytics import (
    IncompatibleSnapshotsError,
    InvalidTimeIntervalError,
    calculate_growth_metrics,
)


class CatalogNotFoundError(LookupError):
    """Raised when a public catalog lookup cannot find an enabled booru."""

    def __init__(self, booru_id: uuid.UUID) -> None:
        super().__init__("Booru not found")
        self.booru_id = booru_id


class GrowthUnavailableReason(StrEnum):
    INSUFFICIENT_HISTORY = "insufficient_history"
    INCOMPATIBLE_SNAPSHOTS = "incompatible_snapshots"
    INVALID_INTERVAL = "invalid_interval"


@dataclass(frozen=True)
class TotalPostsRecord:
    value: int
    provenance: MetricProvenance
    unit: Literal["posts"] = "posts"


@dataclass(frozen=True)
class SnapshotRecord:
    id: uuid.UUID
    booru_id: uuid.UUID
    captured_at: datetime
    total_posts: TotalPostsRecord | None


@dataclass(frozen=True)
class BooruRecord:
    id: uuid.UUID
    name: str
    canonical_url: str
    adapter_family: str
    adapter_name: str | None
    latest_snapshot: SnapshotRecord | None


@dataclass(frozen=True)
class GrowthAvailableRecord:
    booru_id: uuid.UUID
    previous_snapshot: SnapshotRecord
    current_snapshot: SnapshotRecord
    posts_delta: int
    elapsed_hours: float
    posts_per_day: float
    provenance: MetricProvenance
    status: Literal["available"] = field(default="available", init=False)


@dataclass(frozen=True)
class GrowthUnavailableRecord:
    booru_id: uuid.UUID
    reason: GrowthUnavailableReason
    detail: str
    status: Literal["unavailable"] = field(default="unavailable", init=False)


GrowthRecord = GrowthAvailableRecord | GrowthUnavailableRecord


@dataclass(frozen=True)
class ComparisonRecord:
    booru: BooruRecord
    growth: GrowthRecord


class CatalogReadService:
    """Bounded, read-only projections for the public product catalog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_boorus(self, *, limit: int, offset: int) -> tuple[BooruRecord, ...]:
        latest_snapshot_id = self._latest_snapshot_id()
        statement = (
            select(Booru, BooruSnapshot)
            .select_from(Booru)
            .outerjoin(BooruSnapshot, BooruSnapshot.id == latest_snapshot_id)
            .where(Booru.is_enabled.is_(True))
            .order_by(func.lower(Booru.name), Booru.id)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            self._project_booru(booru, snapshot)
            for booru, snapshot in rows
        )

    async def get_booru(self, booru_id: uuid.UUID) -> BooruRecord:
        latest_snapshot_id = self._latest_snapshot_id()
        statement = (
            select(Booru, BooruSnapshot)
            .select_from(Booru)
            .outerjoin(BooruSnapshot, BooruSnapshot.id == latest_snapshot_id)
            .where(Booru.id == booru_id, Booru.is_enabled.is_(True))
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            raise CatalogNotFoundError(booru_id)
        booru, snapshot = row
        return self._project_booru(booru, snapshot)

    async def list_snapshots(
        self,
        booru_id: uuid.UUID,
        *,
        limit: int,
    ) -> tuple[SnapshotRecord, ...]:
        _, snapshots = await self._load_snapshots(booru_id, limit=limit)
        return tuple(self._project_snapshot(snapshot) for snapshot in snapshots)

    async def get_growth(self, booru_id: uuid.UUID) -> GrowthRecord:
        _, snapshots = await self._load_snapshots(booru_id, limit=2)
        return self._calculate_growth(booru_id, snapshots)

    async def compare(self, booru_ids: tuple[uuid.UUID, ...]) -> tuple[ComparisonRecord, ...]:
        ranked_snapshots = (
            select(
                BooruSnapshot.id.label("snapshot_id"),
                BooruSnapshot.booru_id.label("booru_id"),
                func.row_number()
                .over(
                    partition_by=BooruSnapshot.booru_id,
                    order_by=(BooruSnapshot.captured_at.desc(), BooruSnapshot.id.desc()),
                )
                .label("snapshot_rank"),
            )
            .where(BooruSnapshot.booru_id.in_(booru_ids))
            .subquery()
        )
        statement = (
            select(Booru, BooruSnapshot, ranked_snapshots.c.snapshot_rank)
            .select_from(Booru)
            .outerjoin(
                ranked_snapshots,
                and_(
                    ranked_snapshots.c.booru_id == Booru.id,
                    ranked_snapshots.c.snapshot_rank <= 2,
                ),
            )
            .outerjoin(
                BooruSnapshot,
                BooruSnapshot.id == ranked_snapshots.c.snapshot_id,
            )
            .where(Booru.id.in_(booru_ids), Booru.is_enabled.is_(True))
            .order_by(Booru.id, ranked_snapshots.c.snapshot_rank)
        )
        rows = (await self._session.execute(statement)).all()

        boorus: dict[uuid.UUID, Booru] = {}
        snapshots_by_booru: dict[uuid.UUID, list[BooruSnapshot]] = {}
        for booru, snapshot, _rank in rows:
            boorus[booru.id] = booru
            snapshots_by_booru.setdefault(booru.id, [])
            if snapshot is not None:
                snapshots_by_booru[booru.id].append(snapshot)

        for booru_id in booru_ids:
            if booru_id not in boorus:
                raise CatalogNotFoundError(booru_id)

        return tuple(
            ComparisonRecord(
                booru=self._project_booru(
                    boorus[booru_id],
                    snapshots_by_booru[booru_id][0]
                    if snapshots_by_booru[booru_id]
                    else None,
                ),
                growth=self._calculate_growth(
                    booru_id,
                    snapshots_by_booru[booru_id],
                ),
            )
            for booru_id in booru_ids
        )

    @staticmethod
    def _latest_snapshot_id() -> object:
        return (
            select(BooruSnapshot.id)
            .where(BooruSnapshot.booru_id == Booru.id)
            .order_by(BooruSnapshot.captured_at.desc(), BooruSnapshot.id.desc())
            .limit(1)
            .correlate(Booru)
            .scalar_subquery()
        )

    async def _load_snapshots(
        self,
        booru_id: uuid.UUID,
        *,
        limit: int,
    ) -> tuple[Booru, list[BooruSnapshot]]:
        statement = (
            select(Booru, BooruSnapshot)
            .select_from(Booru)
            .outerjoin(BooruSnapshot, BooruSnapshot.booru_id == Booru.id)
            .where(Booru.id == booru_id, Booru.is_enabled.is_(True))
            .order_by(
                BooruSnapshot.captured_at.desc().nullslast(),
                BooruSnapshot.id.desc().nullslast(),
            )
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        if not rows:
            raise CatalogNotFoundError(booru_id)
        booru = rows[0][0]
        snapshots = [snapshot for _, snapshot in rows if snapshot is not None]
        return booru, snapshots

    @classmethod
    def _calculate_growth(
        cls,
        booru_id: uuid.UUID,
        snapshots: list[BooruSnapshot],
    ) -> GrowthRecord:
        if len(snapshots) < 2:
            return GrowthUnavailableRecord(
                booru_id=booru_id,
                reason=GrowthUnavailableReason.INSUFFICIENT_HISTORY,
                detail="At least two snapshots are required.",
            )

        current, previous = snapshots[0], snapshots[1]
        try:
            metrics = calculate_growth_metrics(previous, current)
            provenance = MetricProvenance(metrics.provenance)
        except IncompatibleSnapshotsError as error:
            return GrowthUnavailableRecord(
                booru_id=booru_id,
                reason=GrowthUnavailableReason.INCOMPATIBLE_SNAPSHOTS,
                detail=str(error),
            )
        except InvalidTimeIntervalError as error:
            return GrowthUnavailableRecord(
                booru_id=booru_id,
                reason=GrowthUnavailableReason.INVALID_INTERVAL,
                detail=str(error),
            )
        except ValueError:
            return GrowthUnavailableRecord(
                booru_id=booru_id,
                reason=GrowthUnavailableReason.INCOMPATIBLE_SNAPSHOTS,
                detail="Snapshot provenance is not supported.",
            )

        return GrowthAvailableRecord(
            booru_id=booru_id,
            previous_snapshot=cls._project_snapshot(previous),
            current_snapshot=cls._project_snapshot(current),
            posts_delta=metrics.posts_delta,
            elapsed_hours=metrics.elapsed_hours,
            posts_per_day=metrics.posts_per_day,
            provenance=provenance,
        )

    @classmethod
    def _project_booru(
        cls,
        booru: Booru,
        latest_snapshot: BooruSnapshot | None,
    ) -> BooruRecord:
        return BooruRecord(
            id=booru.id,
            name=booru.name,
            canonical_url=booru.canonical_url,
            adapter_family=booru.adapter_family,
            adapter_name=booru.adapter_name,
            latest_snapshot=(
                cls._project_snapshot(latest_snapshot)
                if latest_snapshot is not None
                else None
            ),
        )

    @classmethod
    def _project_snapshot(cls, snapshot: BooruSnapshot) -> SnapshotRecord:
        return SnapshotRecord(
            id=snapshot.id,
            booru_id=snapshot.booru_id,
            captured_at=snapshot.captured_at,
            total_posts=cls._project_total_posts(snapshot.metrics),
        )

    @staticmethod
    def _project_total_posts(metrics: object) -> TotalPostsRecord | None:
        if not isinstance(metrics, dict):
            return None
        envelope = metrics.get("total_posts")
        if not isinstance(envelope, dict):
            return None

        value = envelope.get("value")
        unit = envelope.get("unit")
        if type(value) is not int or value < 0 or unit != "posts":
            return None
        try:
            provenance = MetricProvenance(envelope.get("provenance"))
        except (TypeError, ValueError):
            return None
        return TotalPostsRecord(value=value, provenance=provenance)
