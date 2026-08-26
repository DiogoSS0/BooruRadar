import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar.core.config import get_settings
from booruradar.models import Booru, BooruSnapshot
from booruradar.services.analytics import calculate_growth_metrics, IncompatibleSnapshotsError, InvalidTimeIntervalError

async def run_stats() -> None:
    parser = argparse.ArgumentParser(description="BooruRadar historical analytics CLI")
    parser.add_argument("target", help="The target booru to analyze")
    args = parser.parse_args()

    if args.target != "danbooru":
        print("ANALYTICS=UNAVAILABLE")
        print("REASON=unsupported_target")
        sys.exit(1)

    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            canonical_url = "https://danbooru.donmai.us"
            booru = await session.scalar(
                select(Booru).where(Booru.canonical_url == canonical_url)
            )
            if not booru:
                print("ANALYTICS=UNAVAILABLE")
                print("REASON=insufficient_history")
                print("SNAPSHOT_COUNT=0")
                sys.exit(0)

            snapshots = (await session.execute(
                select(BooruSnapshot)
                .where(BooruSnapshot.booru_id == booru.id)
                .order_by(BooruSnapshot.captured_at.desc())
                .limit(2)
            )).scalars().all()
            
            if len(snapshots) < 2:
                print("ANALYTICS=UNAVAILABLE")
                print("REASON=insufficient_history")
                print(f"SNAPSHOT_COUNT={len(snapshots)}")
                sys.exit(0)

            current, previous = snapshots[0], snapshots[1]
            try:
                metrics = calculate_growth_metrics(previous, current)
            except (IncompatibleSnapshotsError, InvalidTimeIntervalError) as e:
                print("ANALYTICS=UNAVAILABLE")
                print(f"REASON={e.__class__.__name__}")
                sys.exit(0)

            print("ANALYTICS=AVAILABLE")
            print(f"BOORU={booru.name}")
            print(f"PREVIOUS_TOTAL_POSTS={metrics.previous_total_posts}")
            print(f"CURRENT_TOTAL_POSTS={metrics.current_total_posts}")
            print(f"POSTS_DELTA={metrics.posts_delta}")
            print(f"ELAPSED_HOURS={metrics.elapsed_hours}")
            print(f"POSTS_PER_DAY={metrics.posts_per_day}")
            print(f"PROVENANCE={metrics.provenance}")
            
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run_stats())


if __name__ == "__main__":
    main()
