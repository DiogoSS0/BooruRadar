from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

import httpx

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.adapters.gelbooru import GelbooruAdapter
from booruradar.adapters.aggregate import AggregateAdapter, E621Adapter, MoebooruAdapter, PhilomenaAdapter
from booruradar.adapters.counters import (
    DanbooruCounterAdapter, GelbooruHomeCounterAdapter, GelbooruXmlCounterAdapter,
    PhilomenaStatisticsAdapter, ShimmieHomeCounterAdapter, ShuushuuAdapter,
    UnfilteredPhilomenaAdapter,
)
from booruradar.core.enums import AdapterFamily
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
                    subset_of: str | None = None, reviewed_at: date = date(2026, 9, 8),
                    notes: str | None = None) -> SourceClassification:
    return SourceClassification(
        content_rating=ContentRating(rating), categories=tuple(Category(c) for c in categories),
        reference_urls=tuple(references), reviewed_at=reviewed_at, subset_of=subset_of, notes=notes,
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
                                        total_posts_provenance=adapter.total_posts_provenance,
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


def _new_classification(rating: str, categories: tuple[str, ...], *references: str,
                        notes: str | None = None) -> SourceClassification:
    return _classification(rating, categories, *references, reviewed_at=date(2026, 9, 9), notes=notes)


EXPANSION_TARGETS = (
    _aggregate_target(
        "gelbooru", "Gelbooru", "https://gelbooru.com", GelbooruHomeCounterAdapter,
        _new_classification("nsfw", ("anime", "manga", "fan-art", "hentai"),
                            "https://gelbooru.com/index.php?page=aboutus"),
    ),
    _aggregate_target(
        "sakugabooru", "Sakugabooru", "https://www.sakugabooru.com", MoebooruAdapter,
        _new_classification("nsfw", ("anime", "animation"),
                            "https://www.sakugabooru.com/wiki/show?title=tag_guidelines",
                            notes="Animation archive; its rating rules also permit nudity and graphic violence."),
    ),
    _aggregate_target(
        "furbooru", "Furbooru", "https://furbooru.org", UnfilteredPhilomenaAdapter,
        _new_classification("nsfw", ("furry", "anthro", "fan-art"), "https://furbooru.org/pages/rules"),
    ),
    _aggregate_target(
        "tantabus", "Tantabus", "https://tantabus.ai", UnfilteredPhilomenaAdapter,
        _new_classification("nsfw", ("pony", "fan-art", "ai-generated"), "https://tantabus.ai/pages/rules"),
    ),
    _aggregate_target(
        "e6ai", "e6AI", "https://e6ai.net", E621Adapter,
        _new_classification("nsfw", ("furry", "anthro", "ai-generated"), "https://e6ai.net/help/about"),
    ),
    _aggregate_target(
        "xbooru", "Xbooru", "https://xbooru.com", GelbooruXmlCounterAdapter,
        _new_classification("nsfw", ("anime", "fan-art", "hentai"),
                            "https://xbooru.com/", "https://xbooru.com/index.php?page=help&topic=rating"),
    ),
    _aggregate_target(
        "tbib", "The Big ImageBoard", "https://tbib.org", GelbooruXmlCounterAdapter,
        _new_classification("nsfw", ("anime", "manga", "fan-art", "hentai"),
                            "https://tbib.org/", "https://tbib.org/index.php?page=help&topic=rating",
                            notes="An aggregate imageboard with substantial overlap with other boorus."),
    ),
    _aggregate_target(
        "realbooru", "Realbooru", "https://realbooru.com", GelbooruHomeCounterAdapter,
        _new_classification("nsfw", ("photography",), "https://realbooru.com/tos.php"),
    ),
    _aggregate_target(
        "rule34-paheal", "Rule34 Paheal", "https://rule34.paheal.net", ShimmieHomeCounterAdapter,
        _new_classification("nsfw", ("fan-art", "hentai"), "https://rule34.paheal.net/"),
    ),
    _aggregate_target(
        "hypnohub", "HypnoHub", "https://hypnohub.net", GelbooruHomeCounterAdapter,
        _new_classification("nsfw", ("anime", "fan-art", "hentai"),
                            "https://hypnohub.net/", "https://hypnohub.net/index.php?page=help&topic=rating"),
    ),
    _aggregate_target(
        "e-shuushuu", "e-shuushuu", "https://e-shuushuu.net", ShuushuuAdapter,
        _new_classification("nsfw", ("anime", "manga", "fan-art", "cosplay"),
                            "https://e-shuushuu.net/about", "https://e-shuushuu.net/rules",
                            notes="Hentai is prohibited, but artistic nudity is allowed. Excluded from exclusively Safe results."),
    ),
    _aggregate_target(
        "cosbooru", "Cosbooru", "https://cos.lycore.co", DanbooruCounterAdapter,
        _new_classification("nsfw", ("cosplay", "photography"),
                            "https://cos.lycore.co/wiki_pages/help:home",
                            "https://cos.lycore.co/wiki_pages/howto:rate"),
    ),
    _aggregate_target(
        "manebooru", "Manebooru", "https://manebooru.art", PhilomenaStatisticsAdapter,
        _new_classification("nsfw", ("pony", "fan-art"), "https://manebooru.art/pages/rules"),
    ),
    _aggregate_target(
        "ponerpics", "Ponerpics", "https://ponerpics.org", PhilomenaStatisticsAdapter,
        _new_classification("nsfw", ("pony", "fan-art"), "https://ponerpics.org/pages/rules",
                            notes="Pony archive with imports from other communities; collections overlap."),
    ),
)

COLLECTION_TARGETS = MappingProxyType(
    {target.key: target for target in (
        DANBOORU_TARGET, SAFEBOORU_TARGET, KONACHAN_TARGET, KONACHAN_SAFE_TARGET,
        YANDERE_TARGET, E621_TARGET, DERPIBOORU_TARGET, AIBOORU_TARGET, *EXPANSION_TARGETS,
    )}
)


def get_collection_target(key: str) -> CollectionTarget | None:
    return COLLECTION_TARGETS.get(key.lower())


def target_for_url(canonical_url: str) -> CollectionTarget | None:
    return next((target for target in COLLECTION_TARGETS.values()
                 if target.canonical_url == canonical_url.rstrip("/")), None)
