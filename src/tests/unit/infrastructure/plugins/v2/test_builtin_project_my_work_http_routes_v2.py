"""Production V2 ownership tests for the builtin project My Work HTTP row."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.schemas.activity_read_state import (
    ActivityReadEntry,
    ActivityReadStateResponse,
    UpdateActivityReadStateRequest,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_project_my_work_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2


@pytest.mark.unit
def test_project_my_work_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.project_my_work_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/projects/{project_id}/my-work"),
        ("GET", "/api/v1/projects/{project_id}/activity/read-state"),
        ("PUT", "/api/v1/projects/{project_id}/activity/read-state"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"project-my-work"}


@pytest.mark.unit
def test_project_my_work_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="project-my-work-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.project_my_work_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("project-my-work",)


@pytest.mark.unit
async def test_project_my_work_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []
    list_result = object()
    get_result = ActivityReadStateResponse(
        project_id="project-1",
        entries=[],
        authority_revision=0,
    )
    body = UpdateActivityReadStateRequest(
        expected_authority_revision=0,
        entries=[
            ActivityReadEntry(
                entry_id="entry-1",
                entry_revision=1,
                read_at=datetime(2026, 8, 22, tzinfo=UTC),
            )
        ],
    )
    put_result = ActivityReadStateResponse(
        project_id="project-1",
        entries=body.entries,
        authority_revision=1,
    )
    request = object()
    user = object()
    db = object()

    async def list_handler(
        project_id: str,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> Any:
        calls.append(("list", (project_id, request_value, current_user, db_value)))
        return list_result

    async def get_handler(
        project_id: str,
        current_user: object,
        db_value: object,
    ) -> ActivityReadStateResponse:
        calls.append(("get", (project_id, current_user, db_value)))
        return get_result

    async def put_handler(
        project_id: str,
        body_value: UpdateActivityReadStateRequest,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> ActivityReadStateResponse:
        calls.append(("put", (project_id, body_value, request_value, current_user, db_value)))
        return put_result

    monkeypatch.setattr(subject, "_list_project_my_work", list_handler)
    monkeypatch.setattr(subject, "_get_activity_read_state", get_handler)
    monkeypatch.setattr(subject, "_put_activity_read_state", put_handler)

    assert (
        await subject.list_project_my_work_v2(
            project_id="project-1",
            request=request,
            current_user=user,
            db=db,
        )
        is list_result
    )
    assert (
        await subject.get_activity_read_state_v2(
            project_id="project-1",
            current_user=user,
            db=db,
        )
        is get_result
    )
    assert (
        await subject.put_activity_read_state_v2(
            project_id="project-1",
            body=body,
            request=request,
            current_user=user,
            db=db,
        )
        is put_result
    )
    assert calls == [
        ("list", ("project-1", request, user, db)),
        ("get", ("project-1", user, db)),
        ("put", ("project-1", body, request, user, db)),
    ]


@pytest.mark.unit
def test_project_my_work_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_project_my_work_http_routes_definition_v2()

    assert definition.module_ref == subject.PROJECT_MY_WORK_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
