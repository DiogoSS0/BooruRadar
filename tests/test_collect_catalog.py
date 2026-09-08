import asyncio
from unittest.mock import patch

from booruradar.collect_catalog import DAILY_TARGETS, run_catalog_collection


def test_batch_is_sequential_skips_are_successful_and_failures_are_isolated(capsys):
    calls = []
    async def collect(args):
        calls.append(args)
        if args[0] == "safebooru": raise SystemExit(0)
        if args[0] == "konachan": raise SystemExit(1)
        if args[0] == "e621": raise RuntimeError("sensitive detail")
    with patch("booruradar.collect_catalog.run_collection", collect):
        assert asyncio.run(run_catalog_collection()) == 1
    assert calls == [[key] for key in DAILY_TARGETS]
    assert len(calls) == 7
    assert "danbooru" not in DAILY_TARGETS
    output = capsys.readouterr().out
    assert "CATALOG_FAILURES=2" in output
    assert "sensitive detail" not in output


def test_successful_batch_exits_zero(capsys):
    async def collect(args): return None
    with patch("booruradar.collect_catalog.run_collection", collect):
        assert asyncio.run(run_catalog_collection()) == 0
    assert "CATALOG_FAILURES=0" in capsys.readouterr().out
