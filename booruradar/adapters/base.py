from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

import httpx

from booruradar.adapters.evidence import ResponseEvidence
from booruradar.adapters.schemas import (
    CapabilityDiscovery,
    HealthCheck,
    PublicStatistics,
    RecentPostMetadata,
    SiteDetection,
    TagStatistic,
)
from booruradar.core.enums import AdapterFamily


class UnsupportedCapabilityError(RuntimeError):
    """Raised when a caller requests a capability the site cannot provide."""


class AdapterRequestError(httpx.HTTPError):
    """Request failure stripped of request headers and remote response content."""

    def __init__(self, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("adapter HTTP request failed")


class AdapterResponseError(ValueError):
    """Raised when an adapter response cannot be normalized safely."""


class SourceAccessBlockedError(RuntimeError):
    """Raised when a source denies metadata access before normalization."""


class BooruAdapter(ABC):
    """Metadata-only contract implemented by every supported booru family."""

    adapter_name: ClassVar[str]
    family: ClassVar[AdapterFamily]

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client

    @property
    def request_evidence(self) -> tuple[ResponseEvidence, ...]:
        """Return bounded response fingerprints collected by this adapter."""

        return ()

    def clear_request_evidence(self) -> None:
        """Clear response fingerprints before a new collection run."""

    @classmethod
    @abstractmethod
    async def detect(cls, base_url: str, client: httpx.AsyncClient) -> SiteDetection:
        """Report whether the site matches this adapter without changing remote state."""

    @abstractmethod
    async def health_check(self) -> HealthCheck:
        """Check whether the public site/API is reachable and usable."""

    @abstractmethod
    async def discover_capabilities(self) -> CapabilityDiscovery:
        """Discover which metadata operations this site exposes."""

    @abstractmethod
    async def fetch_public_statistics(self) -> PublicStatistics:
        """Collect public site-wide counters without collecting media files."""

    @abstractmethod
    async def fetch_recent_posts(self, *, limit: int = 50) -> Sequence[RecentPostMetadata]:
        """Collect recent post metadata only; implementations must not download images."""

    @abstractmethod
    async def fetch_tag_statistics(
        self,
        *,
        tag_names: Sequence[str] | None = None,
    ) -> Sequence[TagStatistic]:
        """Collect public tag counters, optionally restricted to named tags."""
