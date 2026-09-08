from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

import httpx

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.adapters.gelbooru import GelbooruAdapter
from booruradar.adapters.aggregate import AggregateAdapter, E621Adapter, MoebooruAdapter, PhilomenaAdapter
from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.discovery import Category, ContentRating, SourceClassification
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
    classification: SourceClassification | None = None

    def __post_init__(self) -> None:
        if self.adapter_type.family is not self.adapter_family:
            raise ValueError("target adapter family does not match its adapter type")
        if self.adapter_type.adapter_name != self.adapter_name:
            raise ValueError("target adapter name does not match its adapter type")
        if self.policy.adapter_family is not self.adapter_family:
            raise ValueError("target collection policy does not match its adapter family")

    def create_adapter(self, client: httpx.AsyncClient) -> BooruAdapter:
        return self.adapter_type(self.canonical_url, client)


def _classification(rating: str, categories: tuple[str, ...], *references: str,
                    subset_of: str | None = None) -> SourceClassification:
    return SourceClassification(
        content_rating=ContentRating(rating), categories=tuple(Category(c) for c in categories),
        reference_urls=tuple(references), reviewed_at=date(2026, 9, 8), subset_of=subset_of,
    )


DANBOORU_TARGET = CollectionTarget(
    key="danbooru",
    name="Danbooru",
    canonical_url="https://danbooru.donmai.us",
    adapter_family=AdapterFamily.DANBOORU,
    adapter_name=DanbooruAdapter.adapter_name,
    adapter_type=DanbooruAdapter,
    policy=DANBOORU_SNAPSHOT_POLICY,
    classification=_classification("nsfw", ("anime", "manga", "fan-art", "hentai"),
                                   "https://danbooru.donmai.us/wiki_pages/help:home",
                                   "https://danbooru.donmai.us/wiki_pages/howto:rate"),
)

SAFEBOORU_TARGET = CollectionTarget(
    key="safebooru",
    name="Safebooru",
    canonical_url="https://safebooru.org",
    adapter_family=AdapterFamily.GELBOORU,
    adapter_name=GelbooruAdapter.adapter_name,
    adapter_type=GelbooruAdapter,
    policy=GELBOORU_SNAPSHOT_POLICY,
    classification=_classification("safe", ("anime", "manga", "fan-art"),
                                   "https://safebooru.org/index.php?page=forum&s=view&id=20"),
)


def _aggregate_target(key: str, name: str, url: str, adapter: type[AggregateAdapter],
                      classification: SourceClassification) -> CollectionTarget:
    return CollectionTarget(
        key=key, name=name, canonical_url=url, adapter_family=adapter.family,
        adapter_name=adapter.adapter_name, adapter_type=adapter,
        policy=SnapshotCollectionPolicy(adapter_family=adapter.family,
                                        total_posts_provenance=MetricProvenance.OBSERVED,
                                        total_posts_unit="posts", statistics_path=adapter.statistics_path),
        classification=classification,
    )


KONACHAN_TARGET = _aggregate_target(
    "konachan", "Konachan", "https://konachan.com", MoebooruAdapter,
    _classification("nsfw", ("anime", "wallpapers", "hentai"),
                    "https://konachan.com/wiki/show?title=help:ratings"),
)
KONACHAN_SAFE_TARGET = _aggregate_target(
    "konachan-safe", "Konachan Safe", "https://konachan.net", MoebooruAdapter,
    _classification("safe", ("anime", "wallpapers"),
                    "https://konachan.net/wiki/show?title=help:ratings", subset_of="konachan"),
)
YANDERE_TARGET = _aggregate_target(
    "yandere", "Yande.re", "https://yande.re", MoebooruAdapter,
    _classification("nsfw", ("anime", "manga", "scans", "hentai"), "https://yande.re/wiki/show?title=help:home"),
)
E621_TARGET = _aggregate_target(
    "e621", "e621", "https://e621.net", E621Adapter,
    _classification("nsfw", ("furry", "anthro", "fan-art"), "https://e621.net/help/posts"),
)
DERPIBOORU_TARGET = _aggregate_target(
    "derpibooru", "Derpibooru", "https://derpibooru.org", PhilomenaAdapter,
    _classification("nsfw", ("pony", "fan-art"), "https://derpibooru.org/pages/rules"),
)
AIBOORU_TARGET = CollectionTarget(
    key="aibooru", name="AIBooru", canonical_url="https://aibooru.online",
    adapter_family=AdapterFamily.DANBOORU, adapter_name=DanbooruAdapter.adapter_name,
    adapter_type=DanbooruAdapter, policy=DANBOORU_SNAPSHOT_POLICY,
    classification=_classification("nsfw", ("anime", "ai-generated", "hentai"),
                                   "https://aibooru.online/wiki_pages/help:home"),
)

COLLECTION_TARGETS = MappingProxyType(
    {target.key: target for target in (
        DANBOORU_TARGET, SAFEBOORU_TARGET, KONACHAN_TARGET, KONACHAN_SAFE_TARGET,
        YANDERE_TARGET, E621_TARGET, DERPIBOORU_TARGET, AIBOORU_TARGET,
    )}
)


def get_collection_target(key: str) -> CollectionTarget | None:
    return COLLECTION_TARGETS.get(key.lower())


def target_for_url(canonical_url: str) -> CollectionTarget | None:
    return next((target for target in COLLECTION_TARGETS.values()
                 if target.canonical_url == canonical_url.rstrip("/")), None)
