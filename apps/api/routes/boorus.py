from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas import (
    BooruListResponse,
    BooruResponse,
    CategoryListResponse,
    CategoryResponse,
    ComparisonItemResponse,
    ComparisonResponse,
    FastestGrowthRankingResponse,
    GrowthAvailableResponse,
    GrowthResponse,
    GrowthUnavailableResponse,
    LargestRankingResponse,
    RankingResponse,
    RelativeGrowthRankingResponse,
    SnapshotListResponse,
    SnapshotResponse,
)
from booruradar.core.database import get_session
from booruradar.discovery import CATEGORY_LABELS, CatalogFilters, Category, CategoryMatch, ContentRating
from booruradar.services.catalog import (
    CatalogNotFoundError,
    CatalogReadService,
    GrowthAvailableRecord,
    RankingMode,
    RankingResult,
)


router = APIRouter(prefix="/api/v1", tags=["public catalog"])


async def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogReadService:
    return CatalogReadService(session)


CatalogService = Annotated[CatalogReadService, Depends(get_catalog_service)]


async def get_catalog_filters(
    q: Annotated[str, Query(max_length=100, description="Case-insensitive community name or domain search.")] = "",
    content_rating: Annotated[ContentRating | None, Query(description="safe: exclusively Safe communities; nsfw: includes mixed communities accepting adult content.")] = None,
    category: Annotated[list[Category] | None, Query(max_length=len(Category), description="Repeat to include community categories.")] = None,
    exclude_category: Annotated[list[Category] | None, Query(max_length=len(Category), description="Exclude communities matching any of these categories.")] = None,
    category_match: Annotated[CategoryMatch, Query(description="Require all or any included categories. Exclusions always apply.")] = CategoryMatch.ALL,
) -> CatalogFilters:
    return CatalogFilters(q=q, content_rating=content_rating, category=tuple(category or ()),
                          exclude_category=tuple(exclude_category or ()), category_match=category_match)


DiscoveryFilters = Annotated[CatalogFilters, Depends(get_catalog_filters)]


@router.get("/categories", response_model=CategoryListResponse,
            summary="List supported editorial community categories")
async def list_categories() -> CategoryListResponse:
    return CategoryListResponse(items=[CategoryResponse(key=key, label=label)
                                       for key, label in CATEGORY_LABELS.items()])


def _not_found(error: CatalogNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Booru not found",
    )


def _growth_response(record: object) -> GrowthResponse:
    if isinstance(record, GrowthAvailableRecord):
        return GrowthAvailableResponse.model_validate(record)
    return GrowthUnavailableResponse.model_validate(record)


def _ranking_response(record: RankingResult) -> RankingResponse:
    if record.mode is RankingMode.LARGEST:
        return LargestRankingResponse.model_validate(record)
    if record.mode is RankingMode.FASTEST_GROWTH:
        return FastestGrowthRankingResponse.model_validate(record)
    return RelativeGrowthRankingResponse.model_validate(record)


@router.get(
    "/rankings",
    response_model=RankingResponse,
    summary="Rank enabled boorus from their latest snapshots",
)
async def list_rankings(
    service: CatalogService,
    filters: DiscoveryFilters,
    mode: RankingMode = RankingMode.LARGEST,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> RankingResponse:
    record = await service.rank_boorus(mode=mode, limit=limit, offset=offset, filters=filters)
    return _ranking_response(record)


@router.get(
    "/boorus",
    response_model=BooruListResponse,
    summary="List enabled boorus",
)
async def list_boorus(
    service: CatalogService,
    filters: DiscoveryFilters,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> BooruListResponse:
    records = await service.list_boorus(limit=limit, offset=offset, filters=filters)
    return BooruListResponse(
        items=[BooruResponse.model_validate(record) for record in records],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/boorus/{booru_id}",
    response_model=BooruResponse,
    summary="Get an enabled booru",
)
async def get_booru(
    booru_id: uuid.UUID,
    service: CatalogService,
) -> BooruResponse:
    try:
        record = await service.get_booru(booru_id)
    except CatalogNotFoundError as error:
        raise _not_found(error) from error
    return BooruResponse.model_validate(record)


@router.get(
    "/boorus/{booru_id}/snapshots",
    response_model=SnapshotListResponse,
    summary="List recent public snapshots",
)
async def list_snapshots(
    booru_id: uuid.UUID,
    service: CatalogService,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> SnapshotListResponse:
    try:
        records = await service.list_snapshots(booru_id, limit=limit)
    except CatalogNotFoundError as error:
        raise _not_found(error) from error
    return SnapshotListResponse(
        booru_id=booru_id,
        items=[SnapshotResponse.model_validate(record) for record in records],
        limit=limit,
    )


@router.get(
    "/boorus/{booru_id}/growth",
    response_model=GrowthResponse,
    summary="Calculate growth from the latest snapshots",
)
async def get_growth(
    booru_id: uuid.UUID,
    service: CatalogService,
) -> GrowthResponse:
    try:
        record = await service.get_growth(booru_id)
    except CatalogNotFoundError as error:
        raise _not_found(error) from error
    return _growth_response(record)


@router.get(
    "/compare",
    response_model=ComparisonResponse,
    summary="Compare a small set of enabled boorus",
)
async def compare_boorus(
    service: CatalogService,
    booru_id: Annotated[list[uuid.UUID], Query(min_length=2, max_length=8)],
) -> ComparisonResponse:
    if len(set(booru_id)) != len(booru_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="booru_id values must be unique",
        )
    try:
        records = await service.compare(tuple(booru_id))
    except CatalogNotFoundError as error:
        raise _not_found(error) from error
    return ComparisonResponse(
        items=[
            ComparisonItemResponse(
                booru=BooruResponse.model_validate(record.booru),
                growth=_growth_response(record.growth),
            )
            for record in records
        ],
    )
