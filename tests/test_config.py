from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr, ValidationError

from booruradar.core.config import Settings


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOORURADAR_LOG_LEVEL", "debug")
    monkeypatch.setenv("BOORURADAR_API_PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.api_port == 9000


def test_settings_reject_unknown_log_level() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="verbose", _env_file=None)


@pytest.mark.parametrize(
    ("configured", "normalized"),
    [
        ("postgres://user:pass@db/app", "postgresql+psycopg://user:pass@db/app"),
        ("postgresql://user:pass@db/app", "postgresql+psycopg://user:pass@db/app"),
        (
            "postgresql+psycopg://user:pass@db/app",
            "postgresql+psycopg://user:pass@db/app",
        ),
    ],
)
def test_settings_normalize_provider_postgresql_urls(
    configured: str,
    normalized: str,
) -> None:
    assert Settings(database_url=configured, _env_file=None).database_url == normalized


def test_danbooru_credentials_use_exact_environment_names_and_mask_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DANBOORU_LOGIN",
        "DANBOORU_API_KEY",
        "BOORURADAR_DANBOORU_LOGIN",
        "BOORURADAR_DANBOORU_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    empty_settings = Settings(_env_file=None)
    assert empty_settings.danbooru_login is None
    assert empty_settings.danbooru_api_key is None

    login = f"test-login-{uuid.uuid4().hex}"
    api_key = f"test-key-{uuid.uuid4().hex}"
    monkeypatch.setenv("DANBOORU_LOGIN", login)
    monkeypatch.setenv("DANBOORU_API_KEY", api_key)
    monkeypatch.setenv("BOORURADAR_DANBOORU_LOGIN", "ignored-prefixed-login")
    monkeypatch.setenv("BOORURADAR_DANBOORU_API_KEY", "ignored-prefixed-key")

    settings = Settings(_env_file=None)

    assert isinstance(settings.danbooru_login, SecretStr)
    assert isinstance(settings.danbooru_api_key, SecretStr)
    assert settings.danbooru_login.get_secret_value() == login
    assert settings.danbooru_api_key.get_secret_value() == api_key
    rendered_values = (
        repr(settings),
        repr(settings.model_dump()),
        settings.model_dump_json(),
    )
    assert all(login not in rendered for rendered in rendered_values)
    assert all(api_key not in rendered for rendered in rendered_values)
