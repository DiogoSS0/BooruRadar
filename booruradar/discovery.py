"""Editorial community taxonomy, separate from measured post statistics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit


class ContentRating(StrEnum):
    SAFE = "safe"
    NSFW = "nsfw"


class Category(StrEnum):
    ANIME = "anime"
    MANGA = "manga"
    FAN_ART = "fan-art"
    FURRY = "furry"
    ANTHRO = "anthro"
    PONY = "pony"
    WALLPAPERS = "wallpapers"
    SCANS = "scans"
    AI_GENERATED = "ai-generated"
    HENTAI = "hentai"
    ANIMATION = "animation"
    COSPLAY = "cosplay"
    PHOTOGRAPHY = "photography"


CATEGORY_LABELS = MappingProxyType({
    Category.ANIME: "Anime", Category.MANGA: "Manga", Category.FAN_ART: "Fan art",
    Category.FURRY: "Furry", Category.ANTHRO: "Anthro", Category.PONY: "Pony",
    Category.WALLPAPERS: "Wallpapers", Category.SCANS: "Scans",
    Category.AI_GENERATED: "AI-generated", Category.HENTAI: "Adult hentai",
    Category.ANIMATION: "Animation", Category.COSPLAY: "Cosplay",
    Category.PHOTOGRAPHY: "Photography",
})


class CategoryMatch(StrEnum):
    ALL = "all"
    ANY = "any"


@dataclass(frozen=True)
class SourceClassification:
    content_rating: ContentRating
    categories: tuple[Category, ...]
    reference_urls: tuple[str, ...]
    reviewed_at: date
    subset_of: str | None = None
    basis: str = "editorial"
    notes: str | None = None


def classification_for_url(canonical_url: str) -> SourceClassification | None:
    from booruradar.targets import target_for_url
    target = target_for_url(canonical_url)
    return target.classification if target else None


def public_snapshot_source_url(source_url: str | None) -> str | None:
    """Publish only known aggregate endpoints, never arbitrary stored URLs."""
    from booruradar.targets import COLLECTION_TARGETS
    return next((target.policy.statistics_url(target.canonical_url)
                 for target in COLLECTION_TARGETS.values()
                 if source_url == target.policy.statistics_url(target.canonical_url)), None)


class ClassifiedIdentity:
    canonical_url: str

    @property
    def classification(self) -> SourceClassification | None:
        return classification_for_url(self.canonical_url)


@dataclass(frozen=True)
class CatalogFilters:
    q: str = ""
    content_rating: ContentRating | None = None
    category: tuple[Category, ...] = ()
    exclude_category: tuple[Category, ...] = ()
    category_match: CategoryMatch = CategoryMatch.ALL

    @property
    def active(self) -> bool:
        return bool(self.q.strip() or self.content_rating or self.category or self.exclude_category)

    def matches(self, name: str, canonical_url: str) -> bool:
        query = self.q.strip().casefold()
        if query and query not in name.casefold() and query not in (urlsplit(canonical_url).hostname or "").casefold():
            return False
        classification = classification_for_url(canonical_url)
        if self.content_rating and (classification is None or classification.content_rating != self.content_rating):
            return False
        categories = set(classification.categories) if classification else set()
        if categories.intersection(self.exclude_category):
            return False
        if self.category:
            selected = set(self.category)
            if self.category_match is CategoryMatch.ALL:
                return selected.issubset(categories)
            return bool(selected.intersection(categories))
        return True
