import asyncio
import sys
import uuid
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

import pytest
from sqlalchemy import select

from booruradar.models import Booru, BooruSnapshot
from booruradar.stats import run_stats

def booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Danbooru",
        canonical_url="https://danbooru.donmai.us",
        adapter_family="danbooru",
        adapter_name="danbooru",
    )

def snapshot(booru_id, posts: int, captured_at: datetime) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        health_status="ok",
        health_provenance="observed",
        capabilities=[],
        capabilities_provenance="estimated",
        metrics={"total_posts": {"value": posts, "provenance": "estimated", "unit": "posts"}},
        source_url="https://danbooru.donmai.us",
    )

class FakeEngine:
    async def dispose(self):
        pass

class ReadOnlySessionContextManager:
    def __init__(self, booru=None, snapshots=None):
        self.booru = booru
        self.snapshots = snapshots or []
        self.executed_statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def commit(self):
        raise AssertionError("Write operation invoked: commit()")

    async def flush(self):
        raise AssertionError("Write operation invoked: flush()")

    def add(self, instance):
        raise AssertionError("Write operation invoked: add()")

    async def delete(self, instance):
        raise AssertionError("Write operation invoked: delete()")

    async def scalar(self, statement):
        stmt_str = str(statement)
        if "boorus" in stmt_str:
            return self.booru
        return None

    async def execute(self, statement):
        self.executed_statements.append(statement)
        class Result:
            def scalars(self):
                class Scalars:
                    def all(self):
                        return self._outer.snapshots
                s = Scalars()
                s._outer = self
                return s
        r = Result()
        r.snapshots = self.snapshots
        return r

def test_stats_cli_prints_exact_expected_output_with_two_snapshots():
    b = booru()
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    s_current = snapshot(b.id, 12010000, t2)
    s_previous = snapshot(b.id, 12000000, t1)
    
    session_mock = ReadOnlySessionContextManager(booru=b, snapshots=[s_current, s_previous])
    
    with patch("booruradar.stats.AsyncSession", return_value=session_mock), \
         patch("booruradar.stats.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["stats.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout:
         
        asyncio.run(run_stats())
            
        output = mock_stdout.getvalue()
        
        expected_lines = [
            "ANALYTICS=AVAILABLE",
            "BOORU=Danbooru",
            "PREVIOUS_TOTAL_POSTS=12000000",
            "CURRENT_TOTAL_POSTS=12010000",
            "POSTS_DELTA=10000",
            "ELAPSED_HOURS=24.0",
            "POSTS_PER_DAY=10000.0",
            "PROVENANCE=estimated"
        ]
        
        for line in expected_lines:
            assert line in output.splitlines()

def test_stats_cli_performs_zero_http_calls():
    b = booru()
    s_current = snapshot(b.id, 1100, datetime(2026, 1, 2, 12, 0, tzinfo=UTC))
    s_previous = snapshot(b.id, 1000, datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    session_mock = ReadOnlySessionContextManager(booru=b, snapshots=[s_current, s_previous])
    
    with patch("booruradar.stats.AsyncSession", return_value=session_mock), \
         patch("booruradar.stats.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["stats.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO), \
         patch("booruradar.stats.httpx", create=True) as mock_httpx:
         
        asyncio.run(run_stats())
            
        mock_httpx.AsyncClient.assert_not_called()

def test_stats_cli_performs_zero_database_writes():
    b = booru()
    s_current = snapshot(b.id, 1100, datetime(2026, 1, 2, 12, 0, tzinfo=UTC))
    s_previous = snapshot(b.id, 1000, datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    session_mock = ReadOnlySessionContextManager(booru=b, snapshots=[s_current, s_previous])
    
    with patch("booruradar.stats.AsyncSession", return_value=session_mock), \
         patch("booruradar.stats.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["stats.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO):
         
        try:
            asyncio.run(run_stats())
        except AssertionError as e:
            pytest.fail(f"A write operation was invoked: {e}")

def test_query_isolation_by_booru_id():
    b = booru()
    session_mock = ReadOnlySessionContextManager(booru=b, snapshots=[])
    
    with patch("booruradar.stats.AsyncSession", return_value=session_mock), \
         patch("booruradar.stats.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["stats.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO):
         
        with pytest.raises(SystemExit):
            asyncio.run(run_stats())
            
        stmt = session_mock.executed_statements[0]
        stmt_str = str(stmt)
        
        assert "booru_snapshots.booru_id =" in stmt_str
        assert "ORDER BY booru_snapshots.captured_at DESC" in stmt_str
        assert "LIMIT" in stmt_str

def test_unsupported_target():
    with patch("sys.argv", ["stats.py", "unknown"]):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with pytest.raises(SystemExit) as excinfo:
                asyncio.run(run_stats())
            assert excinfo.value.code == 1
            assert "ANALYTICS=UNAVAILABLE" in mock_stdout.getvalue()

def test_fewer_than_two_snapshots_insufficient_history():
    b = booru()
    s1 = snapshot(b.id, 1000, datetime.now(UTC))
    session_mock = ReadOnlySessionContextManager(booru=b, snapshots=[s1])
    
    with patch("booruradar.stats.AsyncSession", return_value=session_mock), \
         patch("booruradar.stats.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["stats.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout:
         
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(run_stats())
            
        assert excinfo.value.code == 0
        output = mock_stdout.getvalue()
        assert "ANALYTICS=UNAVAILABLE" in output
        assert "REASON=insufficient_history" in output
        assert "SNAPSHOT_COUNT=1" in output
