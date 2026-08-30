import base64
import asyncio
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from booruradar.adapters import SourceAccessBlockedError
from booruradar.collect import (
    _collection_client_options,
    run_collection,
)
from booruradar.core.config import Settings
from booruradar.models import Booru, BooruSnapshot
from booruradar.core.enums import CrawlRunStatus
from booruradar.services.snapshot_collection import SnapshotCollectionResult
from booruradar.models.crawl_run import CrawlRun


@asynccontextmanager
async def _acquired_collection_lock(_engine, _target_key):
    yield True


@pytest.fixture(autouse=True)
def acquire_collection_lock_for_cli_unit_tests():
    with patch("booruradar.collect.collection_lock", _acquired_collection_lock):
        yield


def make_booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Danbooru",
        canonical_url="https://danbooru.donmai.us",
        adapter_family="danbooru",
        adapter_name="danbooru",
    )

def make_snapshot(booru_id) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=datetime.now(UTC),
        health_status="ok",
        health_provenance="observed",
        capabilities=[],
        capabilities_provenance="estimated",
        metrics={"total_posts": {"value": 123, "provenance": "estimated", "unit": "posts"}},
        source_url="https://danbooru.donmai.us",
    )

class FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True

class FakeSessionContextManager:
    def __init__(self, booru=None, latest_snapshot=None):
        self.booru = booru
        self.latest_snapshot = latest_snapshot
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        pass

    async def scalar(self, statement):
        stmt_str = str(statement)
        if "boorus" in stmt_str:
            return self.booru
        if "booru_snapshots" in stmt_str:
            return self.latest_snapshot
        return None

def test_unknown_target_rejected():
    with patch.object(sys, "argv", ["collect.py", "unknown_target"]):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with pytest.raises(SystemExit) as excinfo:
                asyncio.run(run_collection())
            
            assert excinfo.value.code == 1
            output = mock_stdout.getvalue()
            assert "COLLECTION=FAILED" in output
            assert "Unknown target" in output

def test_missing_booru_created():
    session_mock = FakeSessionContextManager(booru=None, latest_snapshot=None)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect, \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout:
         
        mock_collect.return_value = SnapshotCollectionResult(
            crawl_run=CrawlRun(id=uuid.uuid4(), booru_id=uuid.uuid4(), adapter_name="danbooru", status=CrawlRunStatus.SUCCEEDED, started_at=datetime.now(UTC), details={}),
            snapshot=make_snapshot(uuid.uuid4())
        )
        
        asyncio.run(run_collection())
            
        assert len(session_mock.added) == 1
        assert isinstance(session_mock.added[0], Booru)
        assert session_mock.added[0].name == "Danbooru"
        assert "COLLECTION=SUCCEEDED" in mock_stdout.getvalue()

def test_existing_booru_reused():
    existing_booru = make_booru()
    session_mock = FakeSessionContextManager(booru=existing_booru, latest_snapshot=None)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect, \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout:
         
        mock_collect.return_value = SnapshotCollectionResult(
            crawl_run=CrawlRun(id=uuid.uuid4(), booru_id=existing_booru.id, adapter_name="danbooru", status=CrawlRunStatus.SUCCEEDED, started_at=datetime.now(UTC), details={}),
            snapshot=make_snapshot(existing_booru.id)
        )
        
        asyncio.run(run_collection())
            
        assert len(session_mock.added) == 0

def test_successful_collection_delegates_to_existing_collection_service():
    existing_booru = make_booru()
    session_mock = FakeSessionContextManager(booru=existing_booru, latest_snapshot=None)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect, \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout:
         
        mock_collect.return_value = SnapshotCollectionResult(
            crawl_run=CrawlRun(id=uuid.uuid4(), booru_id=existing_booru.id, adapter_name="danbooru", status=CrawlRunStatus.SUCCEEDED, started_at=datetime.now(UTC), details={}),
            snapshot=make_snapshot(existing_booru.id)
        )
        
        asyncio.run(run_collection())
            
        mock_collect.assert_awaited_once()
        args, kwargs = mock_collect.call_args
        assert args[1] == existing_booru
        assert args[2].adapter_name == "danbooru"

def test_recent_snapshot_causes_skip():
    existing_booru = make_booru()
    recent_snapshot = make_snapshot(existing_booru.id)
    recent_snapshot.captured_at = datetime.now(UTC) - timedelta(hours=1)
    
    session_mock = FakeSessionContextManager(booru=existing_booru, latest_snapshot=recent_snapshot)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
         patch("booruradar.collect.httpx.AsyncClient") as mock_client:
         
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(run_collection())
            
        assert excinfo.value.code == 0
        output = mock_stdout.getvalue()
        assert "COLLECTION=SKIPPED" in output
        assert "REASON=minimum_interval" in output
        mock_client.assert_not_called()

def test_skipped_run_makes_zero_http_calls():
    # Identical to above test but duplicated to explicitly satisfy checklist
    test_recent_snapshot_causes_skip()

def test_force_bypasses_interval_only():
    existing_booru = make_booru()
    recent_snapshot = make_snapshot(existing_booru.id)
    recent_snapshot.captured_at = datetime.now(UTC) - timedelta(hours=1)
    
    session_mock = FakeSessionContextManager(booru=existing_booru, latest_snapshot=recent_snapshot)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["collect.py", "danbooru", "--force"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect:
         
        mock_collect.return_value = SnapshotCollectionResult(
            crawl_run=CrawlRun(id=uuid.uuid4(), booru_id=existing_booru.id, adapter_name="danbooru", status=CrawlRunStatus.SUCCEEDED, started_at=datetime.now(UTC), details={}),
            snapshot=make_snapshot(existing_booru.id)
        )
        
        asyncio.run(run_collection())
            
        mock_collect.assert_awaited_once()

def test_force_does_not_bypass_quality_failures():
    existing_booru = make_booru()
    recent_snapshot = make_snapshot(existing_booru.id)
    recent_snapshot.captured_at = datetime.now(UTC) - timedelta(hours=1)
    
    session_mock = FakeSessionContextManager(booru=existing_booru, latest_snapshot=recent_snapshot)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["collect.py", "danbooru", "--force"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect:
         
        mock_collect.side_effect = Exception("Suspicious observation")
        
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(run_collection())
            
        assert excinfo.value.code == 1
        output = mock_stdout.getvalue()
        assert "COLLECTION=FAILED" in output
        assert "ERROR=Exception: collection failed" in output

def test_failure_returns_non_zero_exit_code():
    session_mock = FakeSessionContextManager(booru=make_booru(), latest_snapshot=None)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect:
         
        mock_collect.side_effect = Exception("Connection error")
        
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(run_collection())
            
        assert excinfo.value.code == 1

def test_output_contains_no_raw_media_data():
    session_mock = FakeSessionContextManager(booru=make_booru(), latest_snapshot=None)
    
    with patch("booruradar.collect.AsyncSession", return_value=session_mock), \
         patch("booruradar.collect.create_async_engine", return_value=FakeEngine()), \
         patch("sys.argv", ["collect.py", "danbooru"]), \
         patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
         patch("booruradar.collect.DanbooruSnapshotCollectionService.collect", new_callable=AsyncMock) as mock_collect:
         
        long_json_error = '{"file_url": "https://cdn.donmai.us/original/123.jpg", "preview_url": "https://...", "bytes": "..."}' * 10
        mock_collect.side_effect = Exception(long_json_error)
        
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(run_collection())
            
        output = mock_stdout.getvalue()
        assert "cdn.donmai.us" not in output
        assert "file_url" not in output


@pytest.mark.parametrize(
    ("login", "api_key"),
    [
        (None, None),
        ("login-only", None),
        (None, "key-only"),
        ("   ", "key"),
        ("login", "   "),
    ],
)
def test_danbooru_auth_is_disabled_without_two_nonempty_values(
    login: str | None,
    api_key: str | None,
) -> None:
    settings = Settings(
        danbooru_login=login,
        danbooru_api_key=api_key,
        _env_file=None,
    )

    options = _collection_client_options(settings, "danbooru")

    assert "auth" not in options


def test_complete_danbooru_credentials_configure_http_basic_auth() -> None:
    login = f"test-login-{uuid.uuid4().hex}"
    api_key = f"test-key-{uuid.uuid4().hex}"
    settings = Settings(
        danbooru_login=login,
        danbooru_api_key=api_key,
        _env_file=None,
    )

    options = _collection_client_options(settings, "danbooru")
    auth = options["auth"]

    assert isinstance(auth, httpx.BasicAuth)
    request = httpx.Request("GET", "https://danbooru.test/posts.json?limit=1")
    authenticated_request = next(auth.auth_flow(request))
    scheme, token = authenticated_request.headers["authorization"].split(" ", 1)
    decoded_credentials = base64.b64decode(token).decode("utf-8")
    assert scheme == "Basic"
    assert decoded_credentials == f"{login}:{api_key}"
    assert login not in str(authenticated_request.url)
    assert api_key not in str(authenticated_request.url)
    assert login not in repr(auth)
    assert api_key not in repr(auth)
    assert login not in repr(options)
    assert api_key not in repr(options)


def test_safebooru_client_options_ignore_danbooru_credentials() -> None:
    login = f"test-login-{uuid.uuid4().hex}"
    api_key = f"test-key-{uuid.uuid4().hex}"
    settings = Settings(
        danbooru_login=login,
        danbooru_api_key=api_key,
        _env_file=None,
    )

    options = _collection_client_options(settings, "safebooru")

    assert "auth" not in options
    assert login not in repr(options)
    assert api_key not in repr(options)


def test_blocked_source_cli_output_never_contains_danbooru_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    login = f"test-login-{uuid.uuid4().hex}"
    api_key = f"test-key-{uuid.uuid4().hex}"
    settings = Settings(
        danbooru_login=login,
        danbooru_api_key=api_key,
        _env_file=None,
    )
    session = FakeSessionContextManager(booru=make_booru(), latest_snapshot=None)

    with (
        patch("booruradar.collect.get_settings", return_value=settings),
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
        ) as collect,
        patch("sys.stdout", new_callable=StringIO) as stdout,
        patch("sys.stderr", new_callable=StringIO) as stderr,
    ):
        client_class.return_value.__aenter__.return_value = object()
        collect.side_effect = SourceAccessBlockedError("source access was blocked")

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["danbooru"]))

    assert exc_info.value.code == 1
    assert isinstance(client_class.call_args.kwargs["auth"], httpx.BasicAuth)
    output = stdout.getvalue() + stderr.getvalue() + caplog.text
    assert "ERROR=SourceAccessBlockedError: source access was blocked" in output
    assert login not in output
    assert api_key not in output


@asynccontextmanager
async def _busy_collection_lock(_engine, _target_key):
    yield False


@pytest.mark.parametrize("force", [False, True])
def test_concurrent_run_skips_before_session_or_http_even_when_forced(force: bool) -> None:
    engine = FakeEngine()
    argv = ["danbooru", "--force"] if force else ["danbooru"]

    with (
        patch("booruradar.collect.collection_lock", _busy_collection_lock),
        patch("booruradar.collect.create_async_engine", return_value=engine),
        patch("booruradar.collect.AsyncSession") as session_class,
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService"
        ) as service_class,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(argv))

    assert exc_info.value.code == 0
    assert stdout.getvalue().splitlines() == [
        "COLLECTION=SKIPPED",
        "TARGET=danbooru",
        "REASON=collection_in_progress",
    ]
    session_class.assert_not_called()
    client_class.assert_not_called()
    service_class.assert_not_called()
    assert engine.disposed is True


def test_settings_failure_is_structured_and_sanitized() -> None:
    secret = f"password={uuid.uuid4().hex}"

    with (
        patch("booruradar.collect.get_settings", side_effect=RuntimeError(secret)),
        patch("booruradar.collect.create_async_engine") as engine_factory,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["danbooru"]))

    assert exc_info.value.code == 1
    output = stdout.getvalue()
    assert "COLLECTION=FAILED" in output
    assert "ERROR=RuntimeError: collection failed" in output
    assert secret not in output
    engine_factory.assert_not_called()


def test_engine_construction_failure_is_structured_and_sanitized() -> None:
    secret = uuid.uuid4().hex
    database_url = f"postgresql+psycopg://user:{secret}@database/app"

    with (
        patch(
            "booruradar.collect.create_async_engine",
            side_effect=RuntimeError(database_url),
        ),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["danbooru"]))

    assert exc_info.value.code == 1
    output = stdout.getvalue()
    assert "COLLECTION=FAILED" in output
    assert "ERROR=RuntimeError: collection failed" in output
    assert secret not in output
    assert "postgresql" not in output


@pytest.mark.parametrize(
    "unsafe_message",
    [
        "api_key=do-not-print",
        "authorization=Basic do-not-print",
        "token=do-not-print",
        "password=do-not-print",
    ],
)
def test_collection_failure_never_echoes_short_secret_text(
    unsafe_message: str,
) -> None:
    session = FakeSessionContextManager(booru=make_booru(), latest_snapshot=None)

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
        ) as collect,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        collect.side_effect = RuntimeError(unsafe_message)
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["danbooru"]))

    assert exc_info.value.code == 1
    output = stdout.getvalue()
    assert "ERROR=RuntimeError: collection failed" in output
    assert unsafe_message not in output
    assert "do-not-print" not in output


def test_session_exit_failure_preserves_committed_success() -> None:
    secret = "password=unsafe-session-close"
    booru = make_booru()

    class SessionExitFailure(FakeSessionContextManager):
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise RuntimeError(secret)

    session = SessionExitFailure(booru=booru, latest_snapshot=None)
    engine = FakeEngine()
    result = SnapshotCollectionResult(
        crawl_run=CrawlRun(
            id=uuid.uuid4(),
            booru_id=booru.id,
            adapter_name="danbooru",
            status=CrawlRunStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            details={},
        ),
        snapshot=make_snapshot(booru.id),
    )

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=engine),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        asyncio.run(run_collection(["danbooru"]))

    output = stdout.getvalue()
    assert "COLLECTION=SUCCEEDED" in output
    assert "COLLECTION=FAILED" not in output
    assert "CLEANUP=FAILED" in output
    assert secret not in output
    assert engine.disposed is True


@asynccontextmanager
async def _release_failure_collection_lock(_engine, _target_key):
    try:
        yield True
    finally:
        raise RuntimeError("password=unsafe-lock-release")


def test_lock_release_failure_preserves_committed_success() -> None:
    booru = make_booru()
    result = SnapshotCollectionResult(
        crawl_run=CrawlRun(
            id=uuid.uuid4(),
            booru_id=booru.id,
            adapter_name="danbooru",
            status=CrawlRunStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            details={},
        ),
        snapshot=make_snapshot(booru.id),
    )

    with (
        patch("booruradar.collect.collection_lock", _release_failure_collection_lock),
        patch(
            "booruradar.collect.AsyncSession",
            return_value=FakeSessionContextManager(booru=booru),
        ),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        asyncio.run(run_collection(["danbooru"]))

    output = stdout.getvalue()
    assert "COLLECTION=SUCCEEDED" in output
    assert "COLLECTION=FAILED" not in output
    assert output.count("CLEANUP=FAILED") == 1
    assert "unsafe-lock-release" not in output


def test_http_client_exit_failure_preserves_committed_success() -> None:
    booru = make_booru()
    result = SnapshotCollectionResult(
        crawl_run=CrawlRun(
            id=uuid.uuid4(),
            booru_id=booru.id,
            adapter_name="danbooru",
            status=CrawlRunStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            details={},
        ),
        snapshot=make_snapshot(booru.id),
    )

    with (
        patch(
            "booruradar.collect.AsyncSession",
            return_value=FakeSessionContextManager(booru=booru),
        ),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        client_class.return_value.__aexit__.side_effect = RuntimeError(
            "password=unsafe-http-close"
        )
        asyncio.run(run_collection(["danbooru"]))

    output = stdout.getvalue()
    assert "COLLECTION=SUCCEEDED" in output
    assert "COLLECTION=FAILED" not in output
    assert output.count("CLEANUP=FAILED") == 1
    assert "unsafe-http-close" not in output


def test_skip_cleanup_failure_emits_one_terminal_result() -> None:
    booru = make_booru()
    recent_snapshot = make_snapshot(booru.id)
    recent_snapshot.captured_at = datetime.now(UTC) - timedelta(hours=1)

    class SessionExitFailure(FakeSessionContextManager):
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise RuntimeError("password=unsafe-skip-close")

    session = SessionExitFailure(booru=booru, latest_snapshot=recent_snapshot)
    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["danbooru"]))

    assert exc_info.value.code == 0
    output = stdout.getvalue()
    assert output.count("COLLECTION=SKIPPED") == 1
    assert "COLLECTION=FAILED" not in output
    assert "COLLECTION=SUCCEEDED" not in output
    assert output.count("CLEANUP=FAILED") == 1
    assert "unsafe-skip-close" not in output
    client_class.assert_not_called()


def test_engine_cleanup_failure_does_not_replace_success_or_leak() -> None:
    secret = "password=unsafe-engine-cleanup"
    booru = make_booru()

    class CleanupFailureEngine(FakeEngine):
        async def dispose(self):
            self.disposed = True
            raise RuntimeError(secret)

    engine = CleanupFailureEngine()
    session = FakeSessionContextManager(booru=booru, latest_snapshot=None)
    result = SnapshotCollectionResult(
        crawl_run=CrawlRun(
            id=uuid.uuid4(),
            booru_id=booru.id,
            adapter_name="danbooru",
            status=CrawlRunStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            details={},
        ),
        snapshot=make_snapshot(booru.id),
    )

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=engine),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch(
            "booruradar.collect.DanbooruSnapshotCollectionService.collect",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        asyncio.run(run_collection(["danbooru"]))

    output = stdout.getvalue()
    assert "COLLECTION=SUCCEEDED" in output
    assert "COLLECTION=FAILED" not in output
    assert "CLEANUP=FAILED" in output
    assert secret not in output
    assert engine.disposed is True
