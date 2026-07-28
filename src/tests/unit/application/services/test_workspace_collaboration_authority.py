"""Contract tests for Workspace Collaboration mutation commands."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationActor,
    WorkspaceCollaborationIdempotencyConflictError,
    WorkspaceCollaborationMutationCommand,
    WorkspaceCollaborationMutationReceipt,
    WorkspaceCollaborationMutationService,
)


class _Repository:
    def __init__(self) -> None:
        self.calls: list[
            tuple[WorkspaceCollaborationActor, WorkspaceCollaborationMutationCommand, str]
        ] = []

    async def current_revision(self, *, actor: WorkspaceCollaborationActor) -> int:
        del actor
        return 0

    async def reserve(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
    ) -> WorkspaceCollaborationMutationReceipt:
        self.calls.append((actor, command, request_hash))
        return WorkspaceCollaborationMutationReceipt(
            receipt_id="receipt-1",
            workspace_id=actor.workspace_id,
            surface=command.surface,
            action=command.action,
            expected_revision=command.expected_revision,
            revision=None,
            duplicate=False,
            dispatch_required=True,
        )

    async def finalize(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
        duplicate: bool,
    ) -> WorkspaceCollaborationMutationReceipt:
        del request_hash
        return WorkspaceCollaborationMutationReceipt(
            receipt_id="receipt-1",
            workspace_id=actor.workspace_id,
            surface=command.surface,
            action=command.action,
            expected_revision=command.expected_revision,
            revision=command.expected_revision + 1,
            duplicate=duplicate,
            dispatch_required=False,
        )


def _actor() -> WorkspaceCollaborationActor:
    return WorkspaceCollaborationActor(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
    )


def _command() -> WorkspaceCollaborationMutationCommand:
    return WorkspaceCollaborationMutationCommand(
        contract_version="2.0.0",
        surface="discussion",
        action="create_post",
        expected_revision=0,
        idempotency_key="workspace-command-0001",
        payload={"title": "Decision", "content": "Ship it"},
    )


@pytest.mark.unit
async def test_workspace_mutation_hash_is_canonical_and_scope_bound() -> None:
    repository = _Repository()
    service = WorkspaceCollaborationMutationService(repository)
    command = _command()

    first = await service.reserve(actor=_actor(), command=command)
    second = await service.reserve(
        actor=_actor(),
        command=replace(command, payload={"content": "Ship it", "title": "Decision"}),
    )

    assert first.dispatch_required is True
    assert second.dispatch_required is True
    assert repository.calls[0][2] == repository.calls[1][2]
    assert len(repository.calls[0][2]) == 64

    await service.reserve(
        actor=replace(_actor(), workspace_id="workspace-2"),
        command=command,
    )
    assert repository.calls[2][2] != repository.calls[0][2]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "message"),
    [
        (replace(_command(), contract_version="1.0.0"), "contract_version"),
        (replace(_command(), surface="notes", action="create_note"), "surface action"),
        (replace(_command(), expected_revision=-1), "expected_revision"),
        (replace(_command(), idempotency_key="short"), "idempotency_key"),
        (replace(_command(), payload={"value": object()}), "JSON"),
    ],
)
async def test_workspace_mutation_rejects_malformed_commands(
    command: WorkspaceCollaborationMutationCommand,
    message: str,
) -> None:
    service = WorkspaceCollaborationMutationService(_Repository())

    with pytest.raises(ValueError, match=message):
        await service.reserve(actor=_actor(), command=command)


@pytest.mark.unit
async def test_workspace_mutation_rejects_same_key_with_different_intent() -> None:
    class _ConflictingRepository(_Repository):
        async def reserve(
            self,
            *,
            actor: WorkspaceCollaborationActor,
            command: WorkspaceCollaborationMutationCommand,
            request_hash: str,
        ) -> WorkspaceCollaborationMutationReceipt:
            del actor, command, request_hash
            raise WorkspaceCollaborationIdempotencyConflictError

    service = WorkspaceCollaborationMutationService(_ConflictingRepository())

    with pytest.raises(WorkspaceCollaborationIdempotencyConflictError):
        await service.reserve(actor=_actor(), command=_command())
