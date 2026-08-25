"""Unit tests for ``DIContainer._require_db``.

These tests intentionally instantiate the container without a session
(the same way ``app.state.container`` is built at startup) to verify the
guard fires with a descriptive message instead of the opaque
``AttributeError: 'NoneType' has no attribute 'execute'`` that surfaced
from deep inside SQLAlchemy when callers forgot ``container.with_db()``.
"""

from __future__ import annotations

import pytest

from src.configuration.di_container import DIContainer


@pytest.mark.unit
class TestRequireDbGuard:
    def test_require_db_returns_session_when_present(self) -> None:
        sentinel = object()
        container = DIContainer(db=None)
        # Exercising the helper directly avoids needing a real session.
        container._db = sentinel  # type: ignore[assignment]
        assert container._require_db("dummy") is sentinel

    def test_require_db_error_includes_provider_name(self) -> None:
        container = DIContainer(db=None)
        with pytest.raises(RuntimeError) as exc_info:
            container._require_db("my_provider")
        msg = str(exc_info.value)
        assert "my_provider" in msg
        assert "with_db" in msg
