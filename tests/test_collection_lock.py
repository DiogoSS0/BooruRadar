from __future__ import annotations

import asyncio
from typing import Any

import pytest

from booruradar.services.collection_lock import collection_lock, collection_lock_key


class FakeConnection:
    def __init__(
        self,
        *,
        acquired: bool,
        released: bool = True,
        fail_commit_on: int | None = None,
        fail_invalidate: bool = False,
    ) -> None:
        self.acquired = acquired
        self.released = released
        self.fail_commit_on = fail_commit_on
        self.statements: list[tuple[str, dict[str, int]]] = []
        self.commits = 0
        self.invalidated = False
        self.fail_invalidate = fail_invalidate

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(
        self,
        statement: object,
        parameters: dict[str, int],
    ) -> bool:
        rendered = str(statement)
        self.statements.append((rendered, parameters))
        if "pg_try_advisory_lock" in rendered:
            return self.acquired
        if "pg_advisory_unlock" in rendered:
            return self.released
        raise AssertionError(f"unexpected statement: {rendered}")

    async def commit(self) -> None:
        self.commits += 1
        if self.commits == self.fail_commit_on:
            raise RuntimeError("commit failed")

    async def invalidate(self) -> None:
        self.invalidated = True
        if self.fail_invalidate:
            raise RuntimeError("invalidation failed")


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_collection_lock_key_is_stable_target_scoped_signed_bigint() -> None:
    danbooru_key = collection_lock_key("danbooru")

    assert danbooru_key == collection_lock_key("  DANBOORU ")
    assert danbooru_key != collection_lock_key("safebooru")
    assert -(2**63) <= danbooru_key < 2**63


def test_acquired_lock_is_committed_and_released() -> None:
    async def exercise() -> None:
        connection = FakeConnection(acquired=True)
        engine = FakeEngine(connection)

        async with collection_lock(engine, "danbooru") as acquired:  # type: ignore[arg-type]
            assert acquired is True
            assert len(connection.statements) == 1

        assert len(connection.statements) == 2
        assert "pg_try_advisory_lock" in connection.statements[0][0]
        assert "pg_advisory_unlock" in connection.statements[1][0]
        assert connection.statements[0][1] == connection.statements[1][1]
        assert connection.commits == 2
        assert connection.invalidated is False

    run(exercise())


def test_busy_lock_does_not_attempt_unlock() -> None:
    async def exercise() -> None:
        connection = FakeConnection(acquired=False)
        engine = FakeEngine(connection)

        async with collection_lock(engine, "danbooru") as acquired:  # type: ignore[arg-type]
            assert acquired is False

        assert len(connection.statements) == 1
        assert "pg_try_advisory_lock" in connection.statements[0][0]
        assert connection.commits == 1
        assert connection.invalidated is False

    run(exercise())


def test_body_failure_still_releases_lock_without_masking_error() -> None:
    async def exercise() -> None:
        connection = FakeConnection(acquired=True)
        engine = FakeEngine(connection)

        with pytest.raises(LookupError, match="original"):
            async with collection_lock(engine, "danbooru"):  # type: ignore[arg-type]
                raise LookupError("original")

        assert len(connection.statements) == 2
        assert "pg_advisory_unlock" in connection.statements[1][0]
        assert connection.invalidated is False

    run(exercise())


def test_acquisition_commit_failure_still_releases_lock() -> None:
    async def exercise() -> None:
        connection = FakeConnection(acquired=True, fail_commit_on=1)
        engine = FakeEngine(connection)

        with pytest.raises(RuntimeError, match="commit failed"):
            async with collection_lock(engine, "danbooru"):  # type: ignore[arg-type]
                raise AssertionError("body must not run")

        assert len(connection.statements) == 2
        assert "pg_advisory_unlock" in connection.statements[1][0]
        assert connection.commits == 2
        assert connection.invalidated is False

    run(exercise())


def test_missing_release_invalidates_connection_and_fails_cleanly() -> None:
    async def exercise() -> None:
        connection = FakeConnection(acquired=True, released=False)
        engine = FakeEngine(connection)

        with pytest.raises(RuntimeError, match="advisory lock was not held"):
            async with collection_lock(engine, "danbooru"):  # type: ignore[arg-type]
                pass

        assert connection.invalidated is True

    run(exercise())


def test_cleanup_double_fault_does_not_mask_body_failure() -> None:
    async def exercise() -> None:
        connection = FakeConnection(
            acquired=True,
            fail_commit_on=2,
            fail_invalidate=True,
        )
        engine = FakeEngine(connection)

        with pytest.raises(LookupError, match="original"):
            async with collection_lock(engine, "danbooru"):  # type: ignore[arg-type]
                raise LookupError("original")

        assert connection.invalidated is True

    run(exercise())
