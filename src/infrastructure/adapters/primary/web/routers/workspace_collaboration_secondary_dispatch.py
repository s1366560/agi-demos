"""Workspace Collaboration dispatchers for roster, resources, files, and topology."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from fastapi import BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_cyber_schemas import CyberGeneCreate, CyberGeneUpdate
from src.application.services.topology_service import TopologyService
from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
)
from src.application.services.workspace_service import WorkspaceService
from src.infrastructure.adapters.primary.web.routers import (
    blackboard,
    cyber_genes,
    topology,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_payload import (
    require_workspace_payload_keys,
    workspace_payload_id,
    workspace_payload_model,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_transaction import (
    WorkspaceFileMutationJournal,
    journal_workspace_file_mutation,
)
from src.infrastructure.adapters.secondary.persistence.models import User


class _RosterRouteArguments(TypedDict):
    tenant_id: str
    project_id: str
    workspace_id: str
    background_tasks: BackgroundTasks
    current_user: User
    db: AsyncSession
    workspace_service: WorkspaceService


class _ScopedRouteArguments(TypedDict):
    tenant_id: str
    project_id: str
    workspace_id: str
    request: Request
    current_user: User
    db: AsyncSession


class _TopologyRouteArguments(TypedDict):
    workspace_id: str
    request: Request
    current_user: User
    db: AsyncSession
    topology_service: TopologyService


async def dispatch_secondary_workspace_mutation(
    *,
    actor: WorkspaceCollaborationActor,
    command: WorkspaceCollaborationMutationCommand,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User,
    db: AsyncSession,
) -> bool:
    """Dispatch one secondary surface and report whether it was handled."""
    if command.surface in {"collaboration", "members"}:
        await _dispatch_workspace_roster(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            background_tasks=background_tasks,
            current_user=current_user,
            db=db,
        )
        return True
    if command.surface == "genes":
        await _dispatch_gene(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
        return True
    if command.surface == "files":
        await _dispatch_file(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
        return True
    if command.surface == "topology":
        await _dispatch_topology(
            workspace_id=actor.workspace_id,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
        return True
    if command.surface == "settings" and command.action == "update_workspace":
        await _dispatch_workspace_settings(
            actor=actor,
            payload=command.payload,
            request=request,
            background_tasks=background_tasks,
            current_user=current_user,
            db=db,
        )
        return True
    return False


async def _dispatch_workspace_roster(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User,
    db: AsyncSession,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import workspaces

    service = workspaces.get_workspace_service(request, db)
    common: _RosterRouteArguments = {
        "tenant_id": actor.tenant_id,
        "project_id": actor.project_id,
        "workspace_id": actor.workspace_id,
        "background_tasks": background_tasks,
        "current_user": current_user,
        "db": db,
        "workspace_service": service,
    }
    if action == "bind_agent":
        await workspaces.bind_workspace_agent(
            payload=workspace_payload_model(workspaces.WorkspaceAgentCreateRequest, payload),
            **common,
        )
    elif action == "update_agent_binding":
        await workspaces.update_workspace_agent(
            workspace_agent_id=workspace_payload_id(payload, "workspace_agent_id"),
            payload=workspace_payload_model(
                workspaces.WorkspaceAgentUpdateRequest,
                payload,
                excluded=("workspace_agent_id",),
            ),
            **common,
        )
    elif action == "unbind_agent":
        binding_id = workspace_payload_id(payload, "workspace_agent_id")
        require_workspace_payload_keys(payload, {"workspace_agent_id"})
        await workspaces.delete_workspace_agent(
            workspace_agent_id=binding_id,
            **common,
        )
    elif action == "add_member":
        await workspaces.add_workspace_member(
            payload=workspace_payload_model(
                workspaces.WorkspaceMemberCreateRequest,
                payload,
            ),
            **common,
        )
    elif action == "update_member_role":
        await workspaces.update_workspace_member(
            user_id=workspace_payload_id(payload, "user_id"),
            payload=workspace_payload_model(
                workspaces.WorkspaceMemberUpdateRequest,
                payload,
                excluded=("user_id",),
            ),
            **common,
        )
    elif action == "remove_member":
        user_id = workspace_payload_id(payload, "user_id")
        require_workspace_payload_keys(payload, {"user_id"})
        await workspaces.remove_workspace_member(user_id=user_id, **common)
    else:
        raise ValueError("workspace roster action is unavailable")


async def _dispatch_gene(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    common: _ScopedRouteArguments = {
        "tenant_id": actor.tenant_id,
        "project_id": actor.project_id,
        "workspace_id": actor.workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
    }
    if action == "create_gene":
        await cyber_genes.create_gene(
            payload=workspace_payload_model(CyberGeneCreate, payload),
            **common,
        )
    elif action == "update_gene":
        await cyber_genes.update_gene(
            gene_id=workspace_payload_id(payload, "gene_id"),
            payload=workspace_payload_model(
                CyberGeneUpdate,
                payload,
                excluded=("gene_id",),
            ),
            **common,
        )
    elif action == "delete_gene":
        gene_id = workspace_payload_id(payload, "gene_id")
        require_workspace_payload_keys(payload, {"gene_id"})
        await cyber_genes.delete_gene(gene_id=gene_id, **common)
    else:
        raise ValueError("gene action is unavailable")


async def _dispatch_file(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    common: _ScopedRouteArguments = {
        "tenant_id": actor.tenant_id,
        "project_id": actor.project_id,
        "workspace_id": actor.workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
    }
    if action == "create_directory":
        await blackboard.create_directory(
            payload=workspace_payload_model(blackboard.MkdirRequest, payload),
            **common,
        )
    elif action == "update_file":
        await blackboard.rename_or_move_file(
            file_id=workspace_payload_id(payload, "file_id"),
            payload=workspace_payload_model(
                blackboard.RenameOrMoveFileRequest,
                payload,
                excluded=("file_id",),
            ),
            **common,
        )
    elif action == "delete_file":
        file_id = workspace_payload_id(payload, "file_id")
        recursive = payload.get("recursive", False)
        if not isinstance(recursive, bool):
            raise ValueError("recursive must be a boolean")
        require_workspace_payload_keys(payload, {"file_id", "recursive"})
        await _journal_blackboard_file_delete(
            request=request,
            workspace_id=actor.workspace_id,
            file_id=file_id,
            recursive=recursive,
            db=db,
        )
        await blackboard.delete_file(
            file_id=file_id,
            recursive=recursive,
            **common,
        )
    elif action == "copy_file":
        copy_id = workspace_payload_id(payload, "file_id")
        await blackboard.copy_file(
            file_id=copy_id,
            payload=workspace_payload_model(
                blackboard.CopyFileRequest,
                payload,
                excluded=("file_id",),
            ),
            **common,
        )
    else:
        raise ValueError("file action is unavailable")


async def _journal_blackboard_file_delete(
    *,
    request: Request,
    workspace_id: str,
    file_id: str,
    recursive: bool,
    db: AsyncSession,
) -> None:
    from src.application.services import blackboard_file_service as file_service_module
    from src.infrastructure.adapters.primary.web.routers.blackboard import (
        _file_service_from_request,
    )

    service = _file_service_from_request(request, db)
    bb_file = None
    descendants = []
    try:
        bb_file = await service._file_repo.find_by_id(file_id)
        if bb_file is not None and bb_file.workspace_id == workspace_id and (
            bb_file.is_directory and recursive
        ):
            child_path = file_service_module._join_child_path(
                bb_file.parent_path,
                bb_file.name,
            )
            descendants = await service._file_repo.find_descendants(
                workspace_id,
                child_path,
            )
    except Exception:
        bb_file = None
        descendants = []

    if bb_file is None:
        return
    storage_root = file_service_module.STORAGE_ROOT.resolve()
    workspace_root = (storage_root / workspace_id).resolve()
    files = [
        item
        for item in (bb_file, *descendants)
        if not item.is_directory and item.storage_key
    ]
    for item in files:
        storage_path = (storage_root / workspace_id / item.storage_key).resolve()

        def stage_deleted_file(
            journal: WorkspaceFileMutationJournal,
            *,
            path: Path = storage_path,
            root: Path = workspace_root,
        ) -> None:
            journal.stage_delete(path, storage_root=root)

        journal_workspace_file_mutation(stage_deleted_file)


async def _dispatch_topology(
    *,
    workspace_id: str,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    service = topology.get_topology_service(request, db)
    common: _TopologyRouteArguments = {
        "workspace_id": workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
        "topology_service": service,
    }
    if action == "create_node":
        await topology.create_node(
            body=workspace_payload_model(topology.TopologyNodeCreate, payload),
            **common,
        )
    elif action == "update_node":
        await topology.update_node(
            node_id=workspace_payload_id(payload, "node_id"),
            body=workspace_payload_model(
                topology.TopologyNodeUpdate,
                payload,
                excluded=("node_id",),
            ),
            **common,
        )
    elif action == "delete_node":
        node_id = workspace_payload_id(payload, "node_id")
        require_workspace_payload_keys(payload, {"node_id"})
        await topology.delete_node(node_id=node_id, **common)
    elif action == "create_edge":
        await topology.create_edge(
            body=workspace_payload_model(topology.TopologyEdgeCreate, payload),
            **common,
        )
    elif action == "update_edge":
        await topology.update_edge(
            edge_id=workspace_payload_id(payload, "edge_id"),
            body=workspace_payload_model(
                topology.TopologyEdgeUpdate,
                payload,
                excluded=("edge_id",),
            ),
            **common,
        )
    elif action == "delete_edge":
        edge_id = workspace_payload_id(payload, "edge_id")
        require_workspace_payload_keys(payload, {"edge_id"})
        await topology.delete_edge(edge_id=edge_id, **common)
    else:
        raise ValueError("topology action is unavailable")


async def _dispatch_workspace_settings(
    *,
    actor: WorkspaceCollaborationActor,
    payload: Mapping[str, object],
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User,
    db: AsyncSession,
) -> None:
    from src.infrastructure.adapters.primary.web.routers import workspaces

    await workspaces.update_workspace(
        tenant_id=actor.tenant_id,
        project_id=actor.project_id,
        workspace_id=actor.workspace_id,
        payload=workspace_payload_model(workspaces.WorkspaceUpdateRequest, payload),
        background_tasks=background_tasks,
        current_user=current_user,
        db=db,
        workspace_service=workspaces.get_workspace_service(request, db),
    )
