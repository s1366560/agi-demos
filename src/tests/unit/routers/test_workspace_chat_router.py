"""Tests for workspace chat router contract publishing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException, status

from src.application.services.workspace_surface_contract import (
    HOSTED,
    NON_AUTHORITATIVE,
    SENSING_CAPABLE,
    SIGNAL_ROLE_KEY,
    SURFACE_BOUNDARY_KEY,
)

# NOTE: the workspace chat HTTP routes are cloned as Avernet Core proxies
# (see workspace_core_routes.py), so end-to-end POST/GET flows no longer
# execute the Python handlers in-process and cannot be exercised with the
# in-memory test client. The router is still covered at the function level
# below: error sanitization, the editor guard, and the hosted/sensing event
# contract applied by the message-service publisher wiring.


@pytest.mark.unit
class TestWorkspaceChatRouter:
    def test_map_error_sanitizes_internal_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(RuntimeError("internal chat backend secret"))

        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.detail == "Internal server error"
        assert "internal" not in exc.detail

    def test_map_error_sanitizes_permission_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(PermissionError("workspace chat secret denied"))

        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Access denied"

    def test_map_error_sanitizes_not_found_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(ValueError("message msg-secret not found"))

        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Workspace message not found"

    def test_map_error_sanitizes_bad_request_value_errors(self):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        exc = workspace_chat._map_error(ValueError("secret message payload invalid"))

        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Invalid workspace chat request"

    @pytest.mark.asyncio
    async def test_send_message_requires_workspace_editor(self, monkeypatch):
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        async def deny_without_editor(
            _db,
            _current_user,
            _tenant_id,
            _project_id,
            _workspace_id,
            *,
            require_editor: bool = False,
        ) -> None:
            assert require_editor is True
            raise HTTPException(status_code=403, detail="Workspace editor access required")

        monkeypatch.setattr(workspace_chat, "require_workspace_access", deny_without_editor)

        with pytest.raises(HTTPException) as exc_info:
            await workspace_chat.send_message(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                payload=workspace_chat.SendMessageRequest(content="Viewer write attempt"),
                request=SimpleNamespace(),
                background_tasks=BackgroundTasks(),
                current_user=SimpleNamespace(id="user-1", email="viewer@example.com"),
                db=AsyncMock(),
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Workspace editor access required"

    @pytest.mark.asyncio
    async def test_chat_event_publisher_applies_hosted_sensing_contract(self, monkeypatch):
        """The chat publisher wiring must stamp hosted/non-authoritative metadata."""
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        publish_mock = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.workspace_events."
            "publish_workspace_event_with_retry",
            publish_mock,
        )

        captured: dict[str, object] = {}

        class _FakeContainer:
            redis_client = object()  # non-None so the publisher is wired

            def with_db(self, _db: object) -> _FakeContainer:
                return self

            def workspace_message_service(self, workspace_event_publisher):
                captured["publisher"] = workspace_event_publisher
                return SimpleNamespace()

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(container=_FakeContainer()))
        )

        workspace_chat.get_message_service(request, db=object())

        publisher = captured["publisher"]
        assert publisher is not None
        await publisher("ws-1", "workspace_message_created", {"message": {"id": "m-1"}})

        publish_kwargs = publish_mock.await_args.kwargs
        assert publish_kwargs["workspace_id"] == "ws-1"
        assert publish_kwargs["metadata"][SURFACE_BOUNDARY_KEY] == HOSTED
        assert publish_kwargs["metadata"]["authority_class"] == NON_AUTHORITATIVE
        assert publish_kwargs["metadata"][SIGNAL_ROLE_KEY] == SENSING_CAPABLE
        assert publish_kwargs["payload"][SURFACE_BOUNDARY_KEY] == HOSTED
        assert publish_kwargs["payload"][SIGNAL_ROLE_KEY] == SENSING_CAPABLE
