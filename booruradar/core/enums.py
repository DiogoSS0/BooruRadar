from __future__ import annotations

from enum import StrEnum


class AdapterFamily(StrEnum):
    DANBOORU = "danbooru"
    GELBOORU = "gelbooru"
    SHIMMIE = "shimmie"
    CUSTOM = "custom"


class MetricProvenance(StrEnum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    OWNER_VERIFIED = "owner_verified"


class CrawlRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
