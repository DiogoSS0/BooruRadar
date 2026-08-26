import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar import __version__
from booruradar.adapters.danbooru import DanbooruAdapter
from booruradar.core.config import get_settings
from booruradar.core.enums import AdapterFamily
from booruradar.models import Booru, BooruSnapshot
from booruradar.services.snapshot_collection import DanbooruSnapshotCollectionService


async def run_collection() -> None:
    parser = argparse.ArgumentParser(description="BooruRadar manual collection CLI")
    parser.add_argument("target", help="The target booru to collect from")
    parser.add_argument("--force", action="store_true", help="Bypass minimum interval protection")
    args = parser.parse_args()

    if args.target != "danbooru":
        print("COLLECTION=FAILED")
        print(f"ERROR=ValueError: Unknown target '{args.target}'")
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
                booru = Booru(
                    id=uuid.uuid4(),
                    name="Danbooru",
                    canonical_url=canonical_url,
                    adapter_family=AdapterFamily.DANBOORU.value,
                    adapter_name="danbooru",
                )
                session.add(booru)
                await session.commit()

            latest_snapshot = await session.scalar(
                select(BooruSnapshot)
                .where(BooruSnapshot.booru_id == booru.id)
                .order_by(BooruSnapshot.captured_at.desc())
                .limit(1)
            )

            if latest_snapshot and not args.force:
                interval = timedelta(hours=20)
                now = datetime.now(UTC)
                captured_at = latest_snapshot.captured_at
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=UTC)
                
                if now - captured_at < interval:
                    print("COLLECTION=SKIPPED")
                    print("REASON=minimum_interval")
                    print(f"LAST_SNAPSHOT_AT={captured_at.isoformat()}")
                    sys.exit(0)

            user_agent = f"BooruRadar/{__version__} (+https://github.com/DiogoSS0/BooruRadar)"
            async with httpx.AsyncClient(headers={"User-Agent": user_agent}) as client:
                adapter = DanbooruAdapter(canonical_url, client)
                service = DanbooruSnapshotCollectionService()
                try:
                    result = await service.collect(session, booru, adapter)
                except Exception as e:
                    print("COLLECTION=FAILED")
                    import re
                    safe_msg = str(e).strip()
                    safe_msg = re.sub(r'https?://[^\s\'"]+', '<url>', safe_msg)
                    safe_msg = re.sub(r'file_url|preview_url|cdn', '<redacted>', safe_msg, flags=re.IGNORECASE)
                    print(f"ERROR={e.__class__.__name__}: {safe_msg[:200]}")
                    sys.exit(1)

            metrics = result.snapshot.metrics
            total_posts_metric = metrics.get("total_posts", {})
            print("COLLECTION=SUCCEEDED")
            print(f"BOORU={booru.name}")
            print(f"SNAPSHOT_ID={result.snapshot.id}")
            print(f"CAPTURED_AT={result.snapshot.captured_at.isoformat()}")
            print(f"TOTAL_POSTS={total_posts_metric.get('value')}")
            print(f"PROVENANCE={total_posts_metric.get('provenance')}")
            print(f"UNIT={total_posts_metric.get('unit')}")
            
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run_collection())


if __name__ == "__main__":
    main()
