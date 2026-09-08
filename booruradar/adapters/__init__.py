"""Public adapter API."""

from booruradar.adapters.base import (
    AdapterRequestError,
    AdapterResponseError,
    BooruAdapter,
    SourceAccessBlockedError,
    UnsupportedCapabilityError,
)
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.adapters.aggregate import E621Adapter, MoebooruAdapter, PhilomenaAdapter
from booruradar.adapters.evidence import ResponseEvidence
from booruradar.adapters.gelbooru import GelbooruAdapter
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
    "AdapterRequestError",
    "AdapterResponseError",
    "AdapterRegistry",
    "BooruAdapter",
    "CapabilityDiscovery",
    "DanbooruAdapter",
    "GelbooruAdapter",
    "HealthCheck",
    "PublicStatistics",
    "RecentPostMetadata",
    "ResponseEvidence",
    "SiteDetection",
    "SourceAccessBlockedError",
    "TagStatistic",
    "UnsupportedCapabilityError",
    "registry",
]

registry.register(DanbooruAdapter)
registry.register(GelbooruAdapter)
registry.register(MoebooruAdapter)
registry.register(E621Adapter)
registry.register(PhilomenaAdapter)
