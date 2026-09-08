"""Daily one-shot collection; Danbooru keeps its existing independent schedule."""
from __future__ import annotations

import asyncio

from booruradar.collect import run_collection
from booruradar.services.snapshot_collection import sanitize_exception_message
from booruradar.targets import COLLECTION_TARGETS


DAILY_TARGETS = tuple(key for key in COLLECTION_TARGETS if key != "danbooru")


async def run_catalog_collection() -> int:
    failures = 0
    for key in DAILY_TARGETS:
        try:
            await run_collection([key])
        except SystemExit as error:
            if error.code not in (None, 0):
                failures += 1
        except Exception as error:
            failures += 1
            print(f"TARGET={key}")
            print(f"ERROR={sanitize_exception_message(error)}")
    print(f"CATALOG_TARGETS={len(DAILY_TARGETS)}")
    print(f"CATALOG_FAILURES={failures}")
    return 1 if failures else 0


def main() -> None:
    raise SystemExit(asyncio.run(run_catalog_collection()))


if __name__ == "__main__":
    main()
