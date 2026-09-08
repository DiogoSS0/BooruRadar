from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar import __version__
from booruradar.core.config import Settings, get_settings
from booruradar.models import Booru, BooruSnapshot
from booruradar.services import (
    DanbooruSnapshotCollectionService,
    SnapshotCollectionService,
    SnapshotCollectionResult,
    sanitize_exception_message,
)
from booruradar.services.collection_lock import collection_lock
from booruradar.targets import COLLECTION_TARGETS, get_collection_target


MINIMUM_COLLECTION_INTERVAL = timedelta(hours=20)


@dataclass(frozen=True)
class _SucceededCollection:
    target_key: str
    booru_name: str
    result: SnapshotCollectionResult
    cleanup_failed: bool = False


@dataclass(frozen=True)
class _SkippedCollection:
    target_key: str
    reason: str
    last_snapshot_at: datetime | None = None


_CollectionOutcome = _SucceededCollection | _SkippedCollection


def _collection_client_options(settings: Settings, target_key: str) -> dict[str, Any]:
    user_agent = (
        f"BooruRadar/{__version__} "
        "(+https://github.com/DiogoSS0/BooruRadar)"
    )
    options: dict[str, Any] = {
        "headers": {"User-Agent": user_agent},
        "timeout": settings.http_timeout_seconds,
    }
    if target_key != "danbooru":
        return options

    login = settings.danbooru_login
    api_key = settings.danbooru_api_key
    if login is None or api_key is None:
        return options
    login_value = login.get_secret_value()
    api_key_value = api_key.get_secret_value()
    if not login_value.strip() or not api_key_value.strip():
        return options
    options["auth"] = httpx.BasicAuth(login_value, api_key_value)
    return options


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BooruRadar manual collection CLI")
    parser.add_argument("target", help="Target booru: " + ", ".join(COLLECTION_TARGETS))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass only the minimum collection interval",
    )
    return parser


def _cli_error_message(error: Exception) -> str:
    """Return only the allowlisted error category used by durable crawl runs."""

    return sanitize_exception_message(error)


async def run_collection(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    target = get_collection_target(args.target)
    if target is None:
        print("COLLECTION=FAILED")
        print("ERROR=ValueError: Unknown target")
        raise SystemExit(1)

    outcome: _CollectionOutcome | None = None
    failure: Exception | None = None
    cleanup_failed = False
    engine = None
    try:
        try:
            settings = get_settings()
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            try:
                async with collection_lock(engine, target.key) as lock_acquired:
                    if not lock_acquired:
                        outcome = _SkippedCollection(
                            target_key=target.key,
                            reason="collection_in_progress",
                        )
                    else:
                        async with AsyncSession(
                            engine, expire_on_commit=False
                        ) as session:
                            outcome = await _collect_locked(
                                session, settings, target, force=args.force
                            )
            except Exception:
                if outcome is None:
                    raise
                cleanup_failed = True
        except Exception as error:
            failure = error
    finally:
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:
                cleanup_failed = True

    if failure is not None:
        print("COLLECTION=FAILED")
        print(f"TARGET={target.key}")
        print(f"ERROR={_cli_error_message(failure)}")
        if cleanup_failed:
            print("CLEANUP=FAILED")
        raise SystemExit(1)

    if isinstance(outcome, _SkippedCollection):
        _print_skip(outcome)
        if cleanup_failed:
            print("CLEANUP=FAILED")
        raise SystemExit(0)

    if outcome is None:
        raise RuntimeError("collection ended without an outcome")
    _print_success(outcome.target_key, outcome.booru_name, outcome.result)
    if outcome.cleanup_failed or cleanup_failed:
        print("CLEANUP=FAILED")


async def _collect_locked(
    session: AsyncSession,
    settings: Settings,
    target: Any,
    *,
    force: bool,
) -> _CollectionOutcome:
    booru = await session.scalar(
        select(Booru).where(Booru.canonical_url == target.canonical_url)
    )
    if booru is None:
        booru = Booru(
            id=uuid.uuid4(),
            name=target.name,
            canonical_url=target.canonical_url,
            adapter_family=target.adapter_family.value,
            adapter_name=target.adapter_name,
            is_enabled=False,
        )
        session.add(booru)
        await session.commit()
    elif (
        booru.adapter_family != target.adapter_family.value
        or booru.adapter_name != target.adapter_name
    ):
        raise ValueError("stored booru adapter metadata does not match the target")

    latest_snapshot = await session.scalar(
        select(BooruSnapshot)
        .where(BooruSnapshot.booru_id == booru.id)
        .order_by(BooruSnapshot.captured_at.desc(), BooruSnapshot.id.desc())
        .limit(1)
    )
    if latest_snapshot is not None and not force:
        captured_at = latest_snapshot.captured_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - captured_at < MINIMUM_COLLECTION_INTERVAL:
            return _SkippedCollection(
                target_key=target.key,
                reason="minimum_interval",
                last_snapshot_at=captured_at,
            )

    client_options = _collection_client_options(settings, target.key)
    result: SnapshotCollectionResult | None = None
    client_cleanup_failed = False
    try:
        async with httpx.AsyncClient(**client_options) as client:
            adapter = target.create_adapter(client)
            if target.key == "danbooru":
                service = DanbooruSnapshotCollectionService()
            else:
                service = SnapshotCollectionService(policy=target.policy)
            service.publish_on_success = booru.is_enabled is False and latest_snapshot is None
            result = await service.collect(session, booru, adapter)
    except Exception:
        if result is None:
            raise
        client_cleanup_failed = True

    return _SucceededCollection(
        target_key=target.key,
        booru_name=booru.name,
        result=result,
        cleanup_failed=client_cleanup_failed,
    )


def _print_skip(outcome: _SkippedCollection) -> None:
    print("COLLECTION=SKIPPED")
    print(f"TARGET={outcome.target_key}")
    print(f"REASON={outcome.reason}")
    if outcome.last_snapshot_at is not None:
        print(f"LAST_SNAPSHOT_AT={outcome.last_snapshot_at.isoformat()}")


def _print_success(
    target_key: str,
    booru_name: str,
    result: SnapshotCollectionResult,
) -> None:
    total_posts = result.snapshot.metrics["total_posts"]
    print("COLLECTION=SUCCEEDED")
    print(f"TARGET={target_key}")
    print(f"BOORU={booru_name}")
    print(f"SNAPSHOT_ID={result.snapshot.id}")
    print(f"CAPTURED_AT={result.snapshot.captured_at.isoformat()}")
    print(f"TOTAL_POSTS={total_posts['value']}")
    print(f"PROVENANCE={total_posts['provenance']}")
    print(f"UNIT={total_posts['unit']}")


def main() -> None:
    raise SystemExit(asyncio.run(run_collection()))


if __name__ == "__main__":
    main()
