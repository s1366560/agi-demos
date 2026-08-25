"""Regression coverage for the Workspace Core-owned cyber-gene surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.application.schemas.workspace_cyber_schemas import CyberGeneCreate, CyberGeneUpdate
from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
)
from src.infrastructure.adapters.primary.web.routers import cyber_genes
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_secondary_dispatch import (
    dispatch_secondary_workspace_mutation,
)

type _LegacyHandlerCall = Callable[[Any], Awaitable[object]]


def _legacy_handler_calls() -> tuple[_LegacyHandlerCall, ...]:
    common = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
    }
    return (
        lambda current_user: cyber_genes.create_gene(
            payload=CyberGeneCreate(name="Gene"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_genes.list_genes(
            category=None,
            is_active=None,
            limit=100,
            offset=0,
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_genes.get_gene(
            gene_id="gene-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_genes.update_gene(
            gene_id="gene-1",
            payload=CyberGeneUpdate(name="Updated"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_genes.delete_gene(
            gene_id="gene-1",
            current_user=current_user,
            **common,
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize("call", _legacy_handler_calls())
async def test_legacy_cyber_gene_handlers_fail_closed_without_local_runtime(
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
def test_cyber_gene_contract_module_has_no_static_sql_or_di_fallback() -> None:
    module_names = vars(cyber_genes)

    assert "get_container_with_db" not in module_names
    assert "get_db" not in module_names
    assert "require_workspace_access" not in module_names


@pytest.mark.unit
async def test_secondary_dispatcher_does_not_execute_local_gene_mutations() -> None:
    handled = await dispatch_secondary_workspace_mutation(
        actor=WorkspaceCollaborationActor(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
        ),
        command=WorkspaceCollaborationMutationCommand(
            contract_version=WORKSPACE_COLLABORATION_CONTRACT_VERSION,
            surface="genes",
            action="create_gene",
            expected_revision=0,
            idempotency_key="gene-command-1",
            payload={"name": "Gene"},
        ),
        request=cast("Any", SimpleNamespace()),
        background_tasks=BackgroundTasks(),
        current_user=cast("Any", SimpleNamespace(id="user-1")),
        db=cast("Any", SimpleNamespace()),
    )

    assert handled is False
