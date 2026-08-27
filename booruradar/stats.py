from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar.core.config import get_settings
from booruradar.models import Booru, BooruSnapshot
from booruradar.services.analytics import (
    IncompatibleSnapshotsError,
    InvalidTimeIntervalError,
    calculate_growth_metrics,
)
from booruradar.targets import get_collection_target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BooruRadar historical analytics CLI")
    parser.add_argument("target", help="Target booru: danbooru or safebooru")
    return parser


async def run_stats(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    target = get_collection_target(args.target)
    if target is None:
        print("ANALYTICS=UNAVAILABLE")
        print("REASON=unsupported_target")
        raise SystemExit(1)

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            booru = await session.scalar(
                select(Booru).where(Booru.canonical_url == target.canonical_url)
            )
            if booru is None:
                print("ANALYTICS=UNAVAILABLE")
                print(f"TARGET={target.key}")
                print("REASON=insufficient_history")
                print("SNAPSHOT_COUNT=0")
                raise SystemExit(0)

            snapshots = (
                await session.execute(
                    select(BooruSnapshot)
                    .where(BooruSnapshot.booru_id == booru.id)
                    .order_by(BooruSnapshot.captured_at.desc(), BooruSnapshot.id.desc())
                    .limit(2)
                )
            ).scalars().all()
            if len(snapshots) < 2:
                print("ANALYTICS=UNAVAILABLE")
                print(f"TARGET={target.key}")
                print("REASON=insufficient_history")
                print(f"SNAPSHOT_COUNT={len(snapshots)}")
                raise SystemExit(0)

            current, previous = snapshots
            try:
                metrics = calculate_growth_metrics(previous, current)
            except (IncompatibleSnapshotsError, InvalidTimeIntervalError) as error:
                print("ANALYTICS=UNAVAILABLE")
                print(f"TARGET={target.key}")
                print(f"REASON={error.__class__.__name__}")
                raise SystemExit(0)

            print("ANALYTICS=AVAILABLE")
            print(f"TARGET={target.key}")
            print(f"BOORU={booru.name}")
            print(f"PREVIOUS_TOTAL_POSTS={metrics.previous_total_posts}")
            print(f"CURRENT_TOTAL_POSTS={metrics.current_total_posts}")
            print(f"POSTS_DELTA={metrics.posts_delta}")
            print(f"ELAPSED_HOURS={metrics.elapsed_hours}")
            print(f"POSTS_PER_DAY={metrics.posts_per_day}")
            print(f"PROVENANCE={metrics.provenance}")
    except Exception:
        print("ANALYTICS=UNAVAILABLE")
        print(f"TARGET={target.key}")
        print("REASON=database_unavailable")
        raise SystemExit(1)
    finally:
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run_stats()))


if __name__ == "__main__":
    main()
