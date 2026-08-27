from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar import __version__
from booruradar.core.config import get_settings
from booruradar.models import Booru, BooruSnapshot
from booruradar.services import (
    DanbooruSnapshotCollectionService,
    SnapshotCollectionService,
    sanitize_exception_message,
)
from booruradar.targets import get_collection_target


MINIMUM_COLLECTION_INTERVAL = timedelta(hours=20)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BooruRadar manual collection CLI")
    parser.add_argument("target", help="Target booru: danbooru or safebooru")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass only the minimum collection interval",
    )
    return parser


def _cli_error_message(error: Exception) -> str:
    """Preserve concise legacy messages without echoing payload-like exception text."""

    message = str(error).strip()
    forbidden = re.compile(
        r"https?://|file_url|sample_url|preview_url|media|cdn|image|bytes|[{}\[\]<>]",
        re.IGNORECASE,
    )
    if message and len(message) <= 160 and forbidden.search(message) is None:
        return f"{error.__class__.__name__}: {message}"
    return sanitize_exception_message(error)


async def run_collection(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    target = get_collection_target(args.target)
    if target is None:
        print("COLLECTION=FAILED")
        print("ERROR=ValueError: Unknown target")
        raise SystemExit(1)

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
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
            if latest_snapshot is not None and not args.force:
                captured_at = latest_snapshot.captured_at
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=UTC)
                if datetime.now(UTC) - captured_at < MINIMUM_COLLECTION_INTERVAL:
                    print("COLLECTION=SKIPPED")
                    print(f"TARGET={target.key}")
                    print("REASON=minimum_interval")
                    print(f"LAST_SNAPSHOT_AT={captured_at.isoformat()}")
                    raise SystemExit(0)

            user_agent = (
                f"BooruRadar/{__version__} "
                "(+https://github.com/DiogoSS0/BooruRadar)"
            )
            async with httpx.AsyncClient(
                headers={"User-Agent": user_agent},
                timeout=settings.http_timeout_seconds,
            ) as client:
                adapter = target.create_adapter(client)
                if target.key == "danbooru":
                    service = DanbooruSnapshotCollectionService()
                else:
                    service = SnapshotCollectionService(policy=target.policy)
                result = await service.collect(session, booru, adapter)

            total_posts = result.snapshot.metrics["total_posts"]
            print("COLLECTION=SUCCEEDED")
            print(f"TARGET={target.key}")
            print(f"BOORU={booru.name}")
            print(f"SNAPSHOT_ID={result.snapshot.id}")
            print(f"CAPTURED_AT={result.snapshot.captured_at.isoformat()}")
            print(f"TOTAL_POSTS={total_posts['value']}")
            print(f"PROVENANCE={total_posts['provenance']}")
            print(f"UNIT={total_posts['unit']}")
    except Exception as error:
        print("COLLECTION=FAILED")
        print(f"TARGET={target.key}")
        print(f"ERROR={_cli_error_message(error)}")
        raise SystemExit(1)
    finally:
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run_collection()))


if __name__ == "__main__":
    main()
