from __future__ import annotations

import pytest
from pydantic import ValidationError

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
