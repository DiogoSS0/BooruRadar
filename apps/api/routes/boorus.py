from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas import (
    BooruListResponse,
    BooruResponse,
    ComparisonItemResponse,
    ComparisonResponse,
    GrowthAvailableResponse,
    GrowthResponse,
    GrowthUnavailableResponse,
    SnapshotListResponse,
    SnapshotResponse,
)
from booruradar.core.database import get_session
from booruradar.services.catalog import (
    CatalogNotFoundError,
    CatalogReadService,
    GrowthAvailableRecord,
)


router = APIRouter(prefix="/api/v1", tags=["public catalog"])


async def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogReadService:
    return CatalogReadService(session)


CatalogService = Annotated[CatalogReadService, Depends(get_catalog_service)]


def _not_found(error: CatalogNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Booru not found",
    )


def _growth_response(record: object) -> GrowthResponse:
    if isinstance(record, GrowthAvailableRecord):
        return GrowthAvailableResponse.model_validate(record)
    return GrowthUnavailableResponse.model_validate(record)


@router.get(
    "/boorus",
    response_model=BooruListResponse,
    summary="List enabled boorus",
)
async def list_boorus(
    service: CatalogService,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> BooruListResponse:
    records = await service.list_boorus(limit=limit, offset=offset)
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
