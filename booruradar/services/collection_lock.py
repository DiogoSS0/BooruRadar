from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


_LOCK_NAMESPACE = "booruradar:scheduled-collection:v1"


def collection_lock_key(target_key: str) -> int:
    """Return a stable signed 64-bit PostgreSQL advisory-lock key per target."""

    material = f"{_LOCK_NAMESPACE}:{target_key.strip().lower()}".encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], byteorder="big", signed=True)


@asynccontextmanager
async def collection_lock(
    engine: AsyncEngine,
    target_key: str,
) -> AsyncIterator[bool]:
    """Try to hold one target's session advisory lock for a complete CLI run.

    The lock uses a dedicated connection because snapshot collection deliberately
    commits more than one database transaction. Closing or invalidating that
    connection also releases PostgreSQL session advisory locks.
    """

    lock_key = collection_lock_key(target_key)
    async with engine.connect() as connection:
        acquired = False
        body_failed = False
        try:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            await connection.commit()
            yield acquired
        except BaseException:
            body_failed = True
            raise
        finally:
            if acquired:
                try:
                    released = bool(
                        await connection.scalar(
                            text("SELECT pg_advisory_unlock(:lock_key)"),
                            {"lock_key": lock_key},
                        )
                    )
                    await connection.commit()
                    if not released:
                        await connection.invalidate()
                        if not body_failed:
                            raise RuntimeError("collection advisory lock was not held")
                except BaseException:
                    try:
                        await connection.invalidate()
                    except BaseException:
                        pass
                    if not body_failed:
                        raise
