"""Public adapter API."""

from booruradar.adapters.base import BooruAdapter, UnsupportedCapabilityError
from booruradar.adapters.registry import AdapterRegistry
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
    "HealthCheck",
    "PublicStatistics",
    "RecentPostMetadata",
    "SiteDetection",
    "TagStatistic",
    "UnsupportedCapabilityError",
]
