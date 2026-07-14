from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.configuration.config import Settings

_DOTENV_DATABASE_URL = "postgresql://dotenv-user:dotenv-password@dotenv.example.test:5432/dotenv_db"
_AMBIENT_DATABASE_URL = (
    "postgresql://ambient-user:ambient-password@ambient.example.test:5432/ambient_db"
)


def _write_database_env(path: Path, database_url: str) -> Path:
    env_file = path / ".env"
    env_file.write_text(f"DATABASE_URL={database_url}\n", encoding="utf-8")
    return env_file


@pytest.mark.unit
def test_database_url_from_dotenv_overrides_ambient_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = _write_database_env(tmp_path, _DOTENV_DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", _AMBIENT_DATABASE_URL)

    settings = Settings(_env_file=env_file)

    assert settings.postgres_url == (
        "postgresql+asyncpg://dotenv-user:dotenv-password@dotenv.example.test:5432/dotenv_db"
    )


@pytest.mark.unit
def test_database_url_cannot_fall_back_to_ambient_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", _AMBIENT_DATABASE_URL)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)


@pytest.mark.unit
@pytest.mark.parametrize("database_url", ["", "   "])
def test_database_url_rejects_empty_dotenv_value(tmp_path: Path, database_url: str) -> None:
    env_file = _write_database_env(tmp_path, database_url)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=env_file)


@pytest.mark.unit
def test_database_url_rejects_non_postgresql_url(tmp_path: Path) -> None:
    env_file = _write_database_env(
        tmp_path,
        "https://invalid-user:invalid-password@database.example.test/app",
    )

    with pytest.raises(ValidationError, match="PostgreSQL") as exc_info:
        Settings(_env_file=env_file)

    assert "invalid-password" not in str(exc_info.value)


@pytest.mark.unit
def test_database_url_is_redacted_from_settings_repr(tmp_path: Path) -> None:
    env_file = _write_database_env(tmp_path, _DOTENV_DATABASE_URL)

    settings = Settings(_env_file=env_file)

    assert "dotenv-password" not in repr(settings)
