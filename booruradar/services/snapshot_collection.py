from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from booruradar.adapters.base import (
    AdapterResponseError,
    BooruAdapter,
    SourceAccessBlockedError,
)
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.core.enums import CrawlRunStatus
from booruradar.models import Booru, BooruSnapshot, CrawlRun
from booruradar.services.inspection import BooruInspectionService
from booruradar.services.quality import (
    HardInvalidObservationError,
    DANBOORU_SNAPSHOT_POLICY,
    SnapshotCollectionPolicy,
    SuspiciousObservationError,
    TotalPostsAnomalyPolicy,
    build_snapshot_candidate,
)


@dataclass(frozen=True)
class SnapshotCollectionResult:
    crawl_run: CrawlRun
    snapshot: BooruSnapshot


def sanitize_exception_message(error: Exception) -> str:
    """Return a bounded failure summary without URLs, payloads, or exception text."""

    exception_name = error.__class__.__name__
    if not exception_name.isidentifier() or len(exception_name) > 100:
        exception_name = "Exception"

    if isinstance(error, SourceAccessBlockedError):
        category = "source access was blocked"
    elif isinstance(error, SuspiciousObservationError):
        category = "candidate blocked by anomaly policy"
    elif isinstance(error, (HardInvalidObservationError, AdapterResponseError, ValidationError)):
        category = "response could not be normalized safely"
    elif isinstance(error, httpx.HTTPError):
        category = "HTTP collection request failed"
    else:
        category = "collection failed"
    return f"{exception_name}: {category}"[:500]


class SnapshotCollectionService:
    """Collect one policy-validated snapshot from a metadata-only adapter."""

    def __init__(
        self,
        *,
        policy: SnapshotCollectionPolicy,
        inspection_service: BooruInspectionService | None = None,
    ) -> None:
        self.policy = policy
        self.inspection_service = inspection_service or BooruInspectionService()

    async def collect(
        self,
        session: AsyncSession,
        booru: Booru,
        adapter: BooruAdapter,
    ) -> SnapshotCollectionResult:
        if booru.id is None:
            raise ValueError("booru must be persisted before collection")
        if adapter.family is not self.policy.adapter_family:
            raise ValueError(
                f"{adapter.adapter_name} adapter is incompatible with "
                f"{self.policy.adapter_family.value} snapshot policy"
            )
        if booru.adapter_family != self.policy.adapter_family.value:
            raise ValueError("booru adapter family is incompatible with snapshot policy")

        booru_id = booru.id
        adapter.clear_request_evidence()
        crawl_run_id = uuid.uuid4()
        crawl_run = CrawlRun(
            id=crawl_run_id,
            booru_id=booru_id,
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
                source_url=self.policy.statistics_url(adapter.base_url),
                policy=self.policy,
            )
            previous_metrics = await session.scalar(
                select(BooruSnapshot.metrics)
                .where(BooruSnapshot.booru_id == booru_id)
                .order_by(BooruSnapshot.captured_at.desc(), BooruSnapshot.id.desc())
                .limit(1)
            )
            quality_flags = self.policy.anomaly_policy.suspicious_flags(
                self.policy.previous_total_posts(previous_metrics),
                candidate.total_posts,
            )
            if quality_flags:
                raise SuspiciousObservationError(quality_flags)

            snapshot = BooruSnapshot(
                id=uuid.uuid4(),
                booru_id=booru_id,
                crawl_run_id=crawl_run_id,
                captured_at=candidate.captured_at,
                health_status=candidate.health_status,
                health_provenance=candidate.health_provenance,
                capabilities=list(candidate.capabilities),
                capabilities_provenance=candidate.capabilities_provenance,
                metrics=candidate.metrics.to_storage(),
                source_url=str(candidate.source_url),
            )
            current_run = await session.get(CrawlRun, crawl_run_id)
            if current_run is None:
                raise RuntimeError("durable crawl run could not be reloaded")
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
            failed_run = await session.get(CrawlRun, crawl_run_id)
            if failed_run is None:
                raise RuntimeError("durable crawl run could not be reloaded after failure") from error
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
        adapter: BooruAdapter,
        *,
        quality_status: str,
        quality_flags: tuple[str, ...] = (),
    ) -> dict[str, object]:
        responses = [item.model_dump(mode="json") for item in adapter.request_evidence]
        return {
            "adapter_name": adapter.adapter_name,
            "adapter_version": getattr(adapter, "adapter_version", "unknown"),
            "source_endpoints": sorted(
                {str(item["endpoint_identifier"]) for item in responses}
            ),
            "responses": responses,
            "quality_status": quality_status,
            "quality_flags": list(quality_flags),
        }

    @staticmethod
    def _classify_failure(error: Exception) -> tuple[str, tuple[str, ...]]:
        if isinstance(error, SourceAccessBlockedError):
            return "collection_failed", ("source_access_blocked",)
        if isinstance(error, SuspiciousObservationError):
            return "suspicious", error.flags
        if isinstance(
            error,
            (HardInvalidObservationError, AdapterResponseError, ValidationError),
        ):
            flags = getattr(error, "flags", ("hard_invalid",))
            return "hard_invalid", tuple(flags)
        if isinstance(error, httpx.HTTPError):
            return "collection_failed", ("http_error",)
        return "collection_failed", ("unexpected_error",)

    @staticmethod
    def _concise_error(error: Exception) -> str:
        return sanitize_exception_message(error)


class DanbooruSnapshotCollectionService(SnapshotCollectionService):
    """Compatibility wrapper for the original modern-Danbooru collection path."""

    def __init__(
        self,
        *,
        inspection_service: BooruInspectionService | None = None,
        anomaly_policy: TotalPostsAnomalyPolicy | None = None,
    ) -> None:
        policy = DANBOORU_SNAPSHOT_POLICY
        if anomaly_policy is not None:
            policy = replace(policy, anomaly_policy=anomaly_policy)
        super().__init__(policy=policy, inspection_service=inspection_service)

    async def collect(
        self,
        session: AsyncSession,
        booru: Booru,
        adapter: DanbooruAdapter,
    ) -> SnapshotCollectionResult:
        return await super().collect(session, booru, adapter)
