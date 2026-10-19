"""Focused fixtures for V2 route-dispatch tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import feature_operation_endpoint_v2


@pytest.fixture
def isolated_feature_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy dispatcher tests focused on dispatch; admission has behavioral tests."""

    async def feature_user() -> object:
        return SimpleNamespace(id="route-test-user", is_superuser=False)

    monkeypatch.setattr(
        feature_operation_endpoint_v2, "get_current_user_from_header_or_query", feature_user
    )
    monkeypatch.setattr(
        feature_operation_endpoint_v2,
        "feature_operation_scopes_v2",
        AsyncMock(return_value=(ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="route-test"),)),
    )
    monkeypatch.setattr(feature_operation_endpoint_v2, "require_feature_operation_v2", AsyncMock())
