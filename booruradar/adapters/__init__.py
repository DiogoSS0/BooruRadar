"""Public adapter API."""

from booruradar.adapters.base import BooruAdapter, UnsupportedCapabilityError
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.adapters.evidence import ResponseEvidence
from booruradar.adapters.registry import AdapterRegistry, registry
from booruradar.adapters.schemas import (
    AdapterCapability,
    CapabilityDiscovery,
    HealthCheck,
    PublicStatistics,
    RecentPostMetadata,
    SiteDetection,
    TagStatistic,
)

__all__ = [
    "AdapterCapability",
    "AdapterRegistry",
    "BooruAdapter",
    "CapabilityDiscovery",
    "DanbooruAdapter",
    "HealthCheck",
    "PublicStatistics",
    "RecentPostMetadata",
    "ResponseEvidence",
    "SiteDetection",
    "TagStatistic",
    "UnsupportedCapabilityError",
    "registry",
]

registry.register(DanbooruAdapter)
