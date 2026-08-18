"""Tests for blackboard API router endpoints."""

from __future__ import annotations

import pytest
from fastapi import status

# NOTE: the blackboard HTTP routes are cloned as Avernet Core proxies (see
# workspace_core_routes.py), so end-to-end POST/GET flows no longer execute
# the Python handlers in-process and cannot be exercised with the in-memory
# test client. The blackboard surface contract (OWNED/AUTHORITATIVE event
# metadata) remains covered at the service layer in
# src/tests/unit/application/services/test_blackboard_service.py, and the
# retired SQL repositories are covered by
# src/tests/unit/infrastructure/workspace_core/test_legacy_sql_repository_retirement.py.


@pytest.mark.unit
class TestBlackboardRouter:
    def test_map_error_sanitizes_internal_errors(self):
        from src.infrastructure.adapters.primary.web.routers import blackboard

        exc = blackboard._map_error(RuntimeError("internal blackboard backend secret"))

        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.detail == "Internal server error"
        assert "internal" not in exc.detail

    def test_map_error_sanitizes_permission_errors(self):
        from src.infrastructure.adapters.primary.web.routers import blackboard

        exc = blackboard._map_error(PermissionError("blackboard secret denied"))

        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Access denied"

    def test_map_error_sanitizes_not_found_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import blackboard

        exc = blackboard._map_error(ValueError("blackboard item item-secret not found"))

        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Blackboard item not found"

    def test_map_error_sanitizes_bad_request_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import blackboard

        exc = blackboard._map_error(ValueError("secret blackboard payload invalid"))

        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Invalid blackboard request"
