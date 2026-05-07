"""Unit tests for ``DIContainer._require_db``.

These tests intentionally instantiate the container without a session
(the same way ``app.state.container`` is built at startup) to verify the
guard fires with a descriptive message instead of the opaque
``AttributeError: 'NoneType' has no attribute 'execute'`` that surfaced
from deep inside SQLAlchemy when callers forgot ``container.with_db()``.
"""

from __future__ import annotations

import logging

import pytest

from src.configuration.di_container import DIContainer


@pytest.mark.unit
class TestRequireDbGuard:
    def test_event_log_repository_without_db_raises(self) -> None:
        container = DIContainer(db=None)
        with pytest.raises(RuntimeError, match="event_log_repository.*with_db"):
            container.event_log_repository()

    def test_webhook_repository_without_db_raises(self) -> None:
        container = DIContainer(db=None)
        with pytest.raises(RuntimeError, match="webhook_repository.*with_db"):
            container.webhook_repository()

    def test_require_db_returns_session_when_present(self) -> None:
        sentinel = object()
        container = DIContainer(db=None)
        # Exercising via the helper directly avoids needing a real session
        # (the providers above already cover the not-None happy path through
        # their existing integration tests).
        container._db = sentinel  # type: ignore[assignment]
        assert container._require_db("dummy") is sentinel

    def test_require_db_error_includes_provider_name(self) -> None:
        container = DIContainer(db=None)
        with pytest.raises(RuntimeError) as exc_info:
            container._require_db("my_provider")
        msg = str(exc_info.value)
        assert "my_provider" in msg
        assert "with_db" in msg

    def test_skill_evolution_plugin_without_db_skips_without_error(self, caplog) -> None:
        container = DIContainer(db=None, session_factory=object())  # type: ignore[arg-type]

        with caplog.at_level(logging.INFO, logger="src.configuration.di_container"):
            plugin = container.skill_evolution_plugin()

        assert plugin is None
        assert "DB-scoped container is required" in caplog.text
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
