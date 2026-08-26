from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from booruradar.adapters.danbooru import DanbooruAdapter, DanbooruResponseError
from booruradar.core.enums import CrawlRunStatus
from booruradar.models import Booru, BooruSnapshot, CrawlRun
from booruradar.services.inspection import BooruInspectionService
from booruradar.services.quality import (
    HardInvalidObservationError,
    SuspiciousObservationError,
    TotalPostsAnomalyPolicy,
    build_snapshot_candidate,
    previous_total_posts,
)


@dataclass(frozen=True)
class SnapshotCollectionResult:
    crawl_run: CrawlRun
    snapshot: BooruSnapshot


class DanbooruSnapshotCollectionService:
    """First vertical collection path from modern Danbooru to one accepted snapshot."""

    def __init__(
        self,
        *,
        inspection_service: BooruInspectionService | None = None,
        anomaly_policy: TotalPostsAnomalyPolicy | None = None,
    ) -> None:
        self.inspection_service = inspection_service or BooruInspectionService()
        self.anomaly_policy = anomaly_policy or TotalPostsAnomalyPolicy()

    async def collect(
        self,
        session: AsyncSession,
        booru: Booru,
        adapter: DanbooruAdapter,
    ) -> SnapshotCollectionResult:
        if booru.id is None:
            raise ValueError("booru must be persisted before collection")

        adapter.clear_request_evidence()
        crawl_run_id = uuid.uuid4()
        crawl_run = CrawlRun(
            id=crawl_run_id,
            booru_id=booru.id,
            adapter_name=adapter.adapter_name,
            status=CrawlRunStatus.RUNNING,
            started_at=datetime.now(UTC),
            details=self._evidence_details(adapter, quality_status="pending"),
        )
        session.add(crawl_run)
        await session.commit()

        try:
            inspection = await self.inspection_service.inspect(
                adapter,
                recent_post_limit=1,
                tag_names=None,
            )
            candidate = build_snapshot_candidate(
                inspection,
                source_url=f"{adapter.base_url}/counts/posts.json",
            )
            previous_metrics = await session.scalar(
                select(BooruSnapshot.metrics)
                .where(BooruSnapshot.booru_id == booru.id)
                .order_by(BooruSnapshot.captured_at.desc())
                .limit(1)
            )
            quality_flags = self.anomaly_policy.suspicious_flags(
                previous_total_posts(previous_metrics),
                candidate.total_posts,
            )
            if quality_flags:
                raise SuspiciousObservationError(quality_flags)

            snapshot = BooruSnapshot(
                id=uuid.uuid4(),
                booru_id=booru.id,
                crawl_run_id=crawl_run_id,
                captured_at=candidate.captured_at,
                health_status=candidate.health_status,
                health_provenance=candidate.health_provenance,
                capabilities=list(candidate.capabilities),
                capabilities_provenance=candidate.capabilities_provenance,
                metrics=candidate.metrics.to_storage(),
                source_url=str(candidate.source_url),
            )
            current_run = await session.get(CrawlRun, crawl_run_id) or crawl_run
            current_run.status = CrawlRunStatus.SUCCEEDED
            current_run.finished_at = datetime.now(UTC)
            current_run.error_message = None
            current_run.details = self._evidence_details(
                adapter,
                quality_status="accepted",
                quality_flags=(),
            )
            session.add(snapshot)
            await session.commit()
            return SnapshotCollectionResult(crawl_run=current_run, snapshot=snapshot)
        except Exception as error:
            await session.rollback()
            failed_run = await session.get(CrawlRun, crawl_run_id) or crawl_run
            quality_status, quality_flags = self._classify_failure(error)
            failed_run.status = CrawlRunStatus.FAILED
            failed_run.finished_at = datetime.now(UTC)
            failed_run.error_message = self._concise_error(error)
            failed_run.details = self._evidence_details(
                adapter,
                quality_status=quality_status,
                quality_flags=quality_flags,
            )
            await session.commit()
            raise

    @staticmethod
    def _evidence_details(
        adapter: DanbooruAdapter,
        *,
        quality_status: str,
        quality_flags: tuple[str, ...] = (),
    ) -> dict[str, object]:
        responses = [item.model_dump(mode="json") for item in adapter.request_evidence]
        return {
            "adapter_name": adapter.adapter_name,
            "adapter_version": adapter.adapter_version,
            "source_endpoints": sorted(
                {str(item["endpoint_identifier"]) for item in responses}
            ),
            "responses": responses,
            "quality_status": quality_status,
            "quality_flags": list(quality_flags),
        }

    @staticmethod
    def _classify_failure(error: Exception) -> tuple[str, tuple[str, ...]]:
        if isinstance(error, SuspiciousObservationError):
            return "suspicious", error.flags
        if isinstance(
            error,
            (HardInvalidObservationError, DanbooruResponseError, ValidationError),
        ):
            flags = getattr(error, "flags", ("hard_invalid",))
            return "hard_invalid", tuple(flags)
        if isinstance(error, httpx.HTTPError):
            return "collection_failed", ("http_error",)
        return "collection_failed", ("unexpected_error",)

    @staticmethod
    def _concise_error(error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        return f"{error.__class__.__name__}: {message}"[:500]
