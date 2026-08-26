from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, RootModel

from booruradar.core.enums import MetricProvenance


MetricValue: TypeAlias = bool | int | float | str | None


class MetricEnvelope(BaseModel):
    """A collected value and the evidence class that produced it."""

    model_config = ConfigDict(frozen=True)

    value: MetricValue
    provenance: MetricProvenance
    unit: str | None = None


class MetricMap(RootModel[dict[str, MetricEnvelope]]):
    """Validates the JSON object stored in snapshot metric columns."""

    def to_storage(self) -> dict[str, dict[str, MetricValue]]:
        return self.model_dump(mode="json")
