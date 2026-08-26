from __future__ import annotations

import logging

import httpx

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.schemas import SiteDetection


logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Small explicit registry for built-in and project-specific adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[BooruAdapter]] = {}

    def register(self, adapter_type: type[BooruAdapter]) -> None:
        name = getattr(adapter_type, "adapter_name", "").strip()
        if not name:
            raise ValueError("adapter_type must define a non-empty adapter_name")
        if name in self._adapters:
            raise ValueError(f"adapter {name!r} is already registered")
        self._adapters[name] = adapter_type

    @property
    def registered_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def create(self, name: str, base_url: str, client: httpx.AsyncClient) -> BooruAdapter:
        try:
            adapter_type = self._adapters[name]
        except KeyError as error:
            raise LookupError(f"unknown adapter {name!r}") from error
        return adapter_type(base_url, client)

    async def detect(self, base_url: str, client: httpx.AsyncClient) -> tuple[SiteDetection, ...]:
        matches: list[SiteDetection] = []
        for name, adapter_type in self._adapters.items():
            try:
                result = await adapter_type.detect(base_url, client)
            except (httpx.HTTPError, ValueError):
                logger.warning("adapter_detection_failed", extra={"adapter": name}, exc_info=True)
                continue
            if result.detected:
                matches.append(result)
        return tuple(matches)


registry = AdapterRegistry()
