from __future__ import annotations

import asyncio

import httpx
from sqlalchemy.exc import OperationalError

from apps.api.main import create_app
from booruradar.core.config import Settings
from booruradar.core.database import get_session


class HealthySession:
    async def execute(self, _statement: object) -> None:
        return None


class UnhealthySession:
    async def execute(self, _statement: object) -> None:
        raise OperationalError("SELECT 1", {}, RuntimeError("offline"))


async def healthy_session() -> HealthySession:
    return HealthySession()


async def unhealthy_session() -> UnhealthySession:
    return UnhealthySession()


def test_liveness_endpoint() -> None:
    async def exercise() -> httpx.Response:
        app = create_app(Settings(environment="test"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_checks_database() -> None:
    async def exercise() -> httpx.Response:
        app = create_app(Settings(environment="test"))
        app.dependency_overrides[get_session] = healthy_session
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_reports_database_failure() -> None:
    async def exercise() -> httpx.Response:
        app = create_app(Settings(environment="test"))
        app.dependency_overrides[get_session] = unhealthy_session
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(exercise())

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
