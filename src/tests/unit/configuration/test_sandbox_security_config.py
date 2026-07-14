from __future__ import annotations

import pytest

from src.configuration.config import Settings


@pytest.mark.unit
def test_shared_pip_cache_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.sandbox_pip_cache_enabled is False


@pytest.mark.unit
def test_shared_pip_cache_can_be_enabled_explicitly() -> None:
    settings = Settings(_env_file=None, SANDBOX_PIP_CACHE_ENABLED="true")

    assert settings.sandbox_pip_cache_enabled is True
