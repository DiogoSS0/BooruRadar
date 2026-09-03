from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from booruradar.core.enums import MetricProvenance
from booruradar.services.catalog import (
    GrowthUnavailableReason,
    RankingIneligibleReason,
)


class ApiSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class TotalPostsResponse(ApiSchema):
    value: Annotated[int, Field(ge=0)]
    provenance: MetricProvenance
    unit: Literal["posts"]


class SnapshotResponse(ApiSchema):
    id: uuid.UUID
    booru_id: uuid.UUID
    captured_at: datetime
    total_posts: TotalPostsResponse | None


class BooruResponse(ApiSchema):
    id: uuid.UUID
    name: str
    canonical_url: str
    adapter_family: str
    adapter_name: str | None
    latest_snapshot: SnapshotResponse | None


class BooruListResponse(ApiSchema):
    items: list[BooruResponse]
    limit: int
    offset: int


class SnapshotListResponse(ApiSchema):
    booru_id: uuid.UUID
    items: list[SnapshotResponse]
    limit: int


class GrowthAvailableResponse(ApiSchema):
    status: Literal["available"]
    booru_id: uuid.UUID
    previous_snapshot: SnapshotResponse
    current_snapshot: SnapshotResponse
    posts_delta: int
    posts_delta_unit: Literal["posts"] = "posts"
    elapsed_hours: Annotated[float, Field(gt=0)]
    posts_per_day: float
    posts_per_day_unit: Literal["posts/day"] = "posts/day"
    provenance: MetricProvenance


class GrowthUnavailableResponse(ApiSchema):
    status: Literal["unavailable"]
    booru_id: uuid.UUID
    reason: GrowthUnavailableReason
    detail: str


GrowthResponse = Annotated[
    GrowthAvailableResponse | GrowthUnavailableResponse,
    Field(discriminator="status"),
]


class ComparisonItemResponse(ApiSchema):
    booru: BooruResponse
    growth: GrowthResponse


class ComparisonResponse(ApiSchema):
    items: list[ComparisonItemResponse]


class RankingIdentityResponse(ApiSchema):
    booru_id: uuid.UUID
    name: str
    canonical_url: str
    adapter_family: str
    adapter_name: str | None


class RankingIneligibleResponse(RankingIdentityResponse):
    rank: None = None
    eligible: Literal[False] = False
    reason: RankingIneligibleReason


class LargestRankingEligibleResponse(RankingIdentityResponse):
    rank: Annotated[int, Field(ge=1)]
    eligible: Literal[True] = True
    value: Annotated[int, Field(ge=0)]
    unit: Literal["posts"]
    provenance: MetricProvenance
    latest_snapshot_id: uuid.UUID
    latest_captured_at: datetime


class GrowthRankingEligibleResponse(RankingIdentityResponse):
    rank: Annotated[int, Field(ge=1)]
    eligible: Literal[True] = True
    value: Annotated[float, Field(allow_inf_nan=False)]
    unit: Literal["posts/day", "percent/day"]
    provenance: MetricProvenance
    latest_snapshot_id: uuid.UUID
    latest_captured_at: datetime
    previous_snapshot_id: uuid.UUID
    previous_captured_at: datetime
    elapsed_hours: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    posts_delta: int
    posts_delta_unit: Literal["posts"] = "posts"


LargestRankingItemResponse = Annotated[
    LargestRankingEligibleResponse | RankingIneligibleResponse,
    Field(discriminator="eligible"),
]

GrowthRankingItemResponse = Annotated[
    GrowthRankingEligibleResponse | RankingIneligibleResponse,
    Field(discriminator="eligible"),
]


class LargestRankingResponse(ApiSchema):
    mode: Literal["largest"]
    unit: Literal["posts"]
    total: Annotated[int, Field(ge=0)]
    eligible_count: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=10_000)]
    items: list[LargestRankingItemResponse]


class FastestGrowthRankingResponse(ApiSchema):
    mode: Literal["fastest_growth"]
    unit: Literal["posts/day"]
    total: Annotated[int, Field(ge=0)]
    eligible_count: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=10_000)]
    items: list[GrowthRankingItemResponse]


class RelativeGrowthRankingResponse(ApiSchema):
    mode: Literal["relative_growth"]
    unit: Literal["percent/day"]
    total: Annotated[int, Field(ge=0)]
    eligible_count: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=10_000)]
    items: list[GrowthRankingItemResponse]


RankingResponse = Annotated[
    LargestRankingResponse
    | FastestGrowthRankingResponse
    | RelativeGrowthRankingResponse,
    Field(discriminator="mode"),
]
