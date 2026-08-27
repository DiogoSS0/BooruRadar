from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import httpx

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.adapters.gelbooru import GelbooruAdapter
from booruradar.core.enums import AdapterFamily
from booruradar.services.quality import (
    DANBOORU_SNAPSHOT_POLICY,
    GELBOORU_SNAPSHOT_POLICY,
    SnapshotCollectionPolicy,
)


@dataclass(frozen=True)
class CollectionTarget:
    key: str
    name: str
    canonical_url: str
    adapter_family: AdapterFamily
    adapter_name: str
    adapter_type: type[BooruAdapter]
    policy: SnapshotCollectionPolicy

    def __post_init__(self) -> None:
        if self.adapter_type.family is not self.adapter_family:
            raise ValueError("target adapter family does not match its adapter type")
        if self.adapter_type.adapter_name != self.adapter_name:
            raise ValueError("target adapter name does not match its adapter type")
        if self.policy.adapter_family is not self.adapter_family:
            raise ValueError("target collection policy does not match its adapter family")

    def create_adapter(self, client: httpx.AsyncClient) -> BooruAdapter:
        return self.adapter_type(self.canonical_url, client)


DANBOORU_TARGET = CollectionTarget(
    key="danbooru",
    name="Danbooru",
    canonical_url="https://danbooru.donmai.us",
    adapter_family=AdapterFamily.DANBOORU,
    adapter_name=DanbooruAdapter.adapter_name,
    adapter_type=DanbooruAdapter,
    policy=DANBOORU_SNAPSHOT_POLICY,
)

SAFEBOORU_TARGET = CollectionTarget(
    key="safebooru",
    name="Safebooru",
    canonical_url="https://safebooru.org",
    adapter_family=AdapterFamily.GELBOORU,
    adapter_name=GelbooruAdapter.adapter_name,
    adapter_type=GelbooruAdapter,
    policy=GELBOORU_SNAPSHOT_POLICY,
)

COLLECTION_TARGETS = MappingProxyType(
    {
        DANBOORU_TARGET.key: DANBOORU_TARGET,
        SAFEBOORU_TARGET.key: SAFEBOORU_TARGET,
    }
)


def get_collection_target(key: str) -> CollectionTarget | None:
    return COLLECTION_TARGETS.get(key.lower())
