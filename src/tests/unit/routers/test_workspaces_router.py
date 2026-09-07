"""Regression coverage for Workspace Core-owned workspace route contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import BackgroundTasks, HTTPException, status
from pydantic import ValidationError

from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
)
from src.application.services.workspace_layout_limits import MAX_WORKSPACE_HEX_COORDINATE
from src.infrastructure.adapters.primary.web.routers import workspaces
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_secondary_dispatch import (
    dispatch_secondary_workspace_mutation,
)

type _LegacyHandlerCall = Callable[[Any], Awaitable[object]]


class _AccessTrap:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"retired workspace handler accessed {name}")


def _legacy_handler_calls() -> tuple[_LegacyHandlerCall, ...]:
    scope = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
    }
    workspace = {**scope, "workspace_id": "workspace-1"}
    return (
        lambda trap: workspaces.create_workspace(
            payload=workspaces.WorkspaceCreateRequest(name="Workspace"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **scope,
        ),
        lambda trap: workspaces.list_workspaces(
            limit=50,
            offset=0,
            request=trap,
            current_user=trap,
            **scope,
        ),
        lambda trap: workspaces.get_workspace(
            request=trap,
            current_user=trap,
            **workspace,
        ),
        lambda trap: workspaces.get_workspace_collaboration_capabilities(
            request=trap,
            current_user=trap,
            **workspace,
        ),
        lambda trap: workspaces.update_workspace(
            payload=workspaces.WorkspaceUpdateRequest(name="Updated"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.delete_workspace(
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.list_workspace_members(
            limit=100,
            offset=0,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.add_workspace_member(
            payload=workspaces.WorkspaceMemberCreateRequest(user_id="user-2"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.update_workspace_member(
            user_id="user-2",
            payload=workspaces.WorkspaceMemberUpdateRequest(role="editor"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.remove_workspace_member(
            user_id="user-2",
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.list_workspace_agents(
            active_only=True,
            limit=100,
            offset=0,
            request=trap,
            current_user=trap,
            **workspace,
        ),
        lambda trap: workspaces.bind_workspace_agent(
            payload=workspaces.WorkspaceAgentCreateRequest(agent_id="agent-1"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.update_workspace_agent(
            workspace_agent_id="binding-1",
            payload=workspaces.WorkspaceAgentUpdateRequest(display_name="Updated"),
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
        lambda trap: workspaces.delete_workspace_agent(
            workspace_agent_id="binding-1",
            background_tasks=trap,
            request=trap,
            current_user=trap,
            db=trap,
            **workspace,
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize("call", _legacy_handler_calls())
async def test_legacy_workspace_handlers_fail_closed_without_local_di(
    call: _LegacyHandlerCall,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call(cast("Any", _AccessTrap()))

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
def test_workspace_contract_module_has_no_static_service_or_di_fallback() -> None:
    retired_names = {
        "WorkspaceService",
        "get_workspace_service",
        "get_db",
        "SqlUserRepository",
        "_map_error",
        "_is_workspace_name_conflict",
        "_publish_pending_workspace_events",
        "_retry_publish_pending_workspace_events",
        "_ensure_workspace_scope",
        "_ensure_project_access_for_workspace_create",
        "_ensure_project_member",
        "_as_mapping",
        "_coerce_use_case",
        "_coerce_workspace_type",
        "_coerce_collaboration_mode",
        "_resolve_use_case",
        "_resolve_collaboration_mode",
        "_workspace_type_for_use_case",
        "_compose_workspace_metadata",
        "_to_workspace_response",
        "_to_member_response",
        "_to_agent_response",
    }

    assert retired_names.isdisjoint(vars(workspaces))


@pytest.mark.unit
def test_workspace_contract_models_remain_stable() -> None:
    assert set(workspaces.WorkspaceCreateRequest.model_fields) == {
        "name",
        "description",
        "metadata",
        "use_case",
        "collaboration_mode",
        "autonomy_profile",
        "sandbox_code_root",
    }
    assert set(workspaces.WorkspaceUpdateRequest.model_fields) == {
        "name",
        "description",
        "is_archived",
        "metadata",
    }
    assert set(workspaces.WorkspaceResponse.model_fields) == {
        "id",
        "tenant_id",
        "project_id",
        "name",
        "created_by",
        "description",
        "is_archived",
        "metadata",
        "office_status",
        "hex_layout_config",
        "created_at",
        "updated_at",
    }
    assert set(workspaces.WorkspaceMemberResponse.model_fields) == {
        "id",
        "workspace_id",
        "user_id",
        "user_email",
        "role",
        "invited_by",
        "created_at",
        "updated_at",
    }
    assert set(workspaces.WorkspaceAgentResponse.model_fields) == {
        "id",
        "workspace_id",
        "agent_id",
        "display_name",
        "description",
        "config",
        "is_active",
        "hex_q",
        "hex_r",
        "theme_color",
        "label",
        "status",
        "created_at",
        "updated_at",
    }


@pytest.mark.unit
def test_workspace_contract_models_keep_validation_boundaries() -> None:
    with pytest.raises(ValidationError):
        workspaces.WorkspaceAgentCreateRequest(
            agent_id="agent-1",
            hex_q=MAX_WORKSPACE_HEX_COORDINATE + 1,
        )
    with pytest.raises(ValidationError):
        workspaces.WorkspaceAgentUpdateRequest.model_validate({"status": "busy"})


@pytest.mark.unit
@pytest.mark.parametrize(
    "surface,action,payload",
    [
        ("collaboration", "bind_agent", {"agent_id": "agent-1"}),
        ("settings", "update_workspace", {"name": "Updated"}),
    ],
)
async def test_secondary_dispatcher_does_not_resolve_legacy_workspace_service(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    action: str,
    payload: dict[str, object],
) -> None:
    def legacy_service_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("secondary dispatcher touched the retired workspace service")

    monkeypatch.setattr(workspaces, "get_workspace_service", legacy_service_trap, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_secondary_workspace_mutation(
            actor=WorkspaceCollaborationActor(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                user_id="user-1",
            ),
            command=WorkspaceCollaborationMutationCommand(
                contract_version=WORKSPACE_COLLABORATION_CONTRACT_VERSION,
                surface=surface,
                action=action,
                expected_revision=0,
                idempotency_key=f"{surface}-command-1",
                payload=payload,
            ),
            request=cast("Any", SimpleNamespace()),
            background_tasks=BackgroundTasks(),
            current_user=cast("Any", SimpleNamespace(id="user-1")),
            db=cast("Any", SimpleNamespace()),
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
