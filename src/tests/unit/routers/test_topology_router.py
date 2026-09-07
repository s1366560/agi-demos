"""Regression coverage for the Workspace Core-owned topology surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
)
from src.application.services.workspace_layout_limits import MAX_WORKSPACE_HEX_COORDINATE
from src.domain.model.workspace.topology_node import TopologyNodeType
from src.infrastructure.adapters.primary.web.routers import topology
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_secondary_dispatch import (
    dispatch_secondary_workspace_mutation,
)

type _LegacyHandlerCall = Callable[[Any], Awaitable[object]]


def _legacy_handler_calls() -> tuple[_LegacyHandlerCall, ...]:
    common = {"workspace_id": "workspace-1"}
    return (
        lambda current_user: topology.create_node(
            body=topology.TopologyNodeCreate(node_type=TopologyNodeType.NOTE, title="Node"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.list_nodes(
            limit=1000,
            offset=0,
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.get_node(
            node_id="node-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.update_node(
            node_id="node-1",
            body=topology.TopologyNodeUpdate(title="Updated"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.delete_node(
            node_id="node-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.create_edge(
            body=topology.TopologyEdgeCreate(
                source_node_id="node-1",
                target_node_id="node-2",
            ),
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.list_edges(
            limit=2000,
            offset=0,
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.get_edge(
            edge_id="edge-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.update_edge(
            edge_id="edge-1",
            body=topology.TopologyEdgeUpdate(label="Updated"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: topology.delete_edge(
            edge_id="edge-1",
            current_user=current_user,
            **common,
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize("call", _legacy_handler_calls())
async def test_legacy_topology_handlers_fail_closed_without_local_runtime(
    call: _LegacyHandlerCall,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call(cast("Any", SimpleNamespace(id="user-1")))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
def test_topology_contract_module_has_no_static_service_or_di_fallback() -> None:
    retired_names = {
        "TopologyService",
        "get_topology_service",
        "get_db",
        "_topology_access_denied_error",
        "_invalid_topology_request_error",
        "_topology_node_not_found_error",
        "_topology_edge_not_found_error",
        "_topology_not_found_error",
        "_is_not_found_error",
        "_serialize_node",
        "_serialize_edge",
        "_publish_topology_event_after_commit",
    }

    assert retired_names.isdisjoint(vars(topology))


@pytest.mark.unit
def test_topology_contract_models_keep_validation_boundaries() -> None:
    with pytest.raises(ValidationError):
        topology.TopologyNodeCreate(
            node_type=TopologyNodeType.NOTE,
            hex_q=MAX_WORKSPACE_HEX_COORDINATE + 1,
        )
    with pytest.raises(ValidationError):
        topology.TopologyEdgeCreate.model_validate(
            {
                "source_node_id": "node-1",
                "target_node_id": "node-2",
                "source_hex_q": 1,
            }
        )


@pytest.mark.unit
async def test_secondary_dispatcher_does_not_execute_local_topology_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def legacy_service_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("secondary dispatcher touched the retired topology service")

    monkeypatch.setattr(topology, "get_topology_service", legacy_service_trap, raising=False)
    handled = await dispatch_secondary_workspace_mutation(
        actor=WorkspaceCollaborationActor(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
        ),
        command=WorkspaceCollaborationMutationCommand(
            contract_version=WORKSPACE_COLLABORATION_CONTRACT_VERSION,
            surface="topology",
            action="create_node",
            expected_revision=0,
            idempotency_key="topology-command-1",
            payload={"node_type": "note"},
        ),
        request=cast("Any", SimpleNamespace()),
        background_tasks=BackgroundTasks(),
        current_user=cast("Any", SimpleNamespace(id="user-1")),
        db=cast("Any", SimpleNamespace()),
    )

    assert handled is False
