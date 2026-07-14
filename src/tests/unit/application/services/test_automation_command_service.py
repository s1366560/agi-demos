from __future__ import annotations

from dataclasses import replace

import pytest

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandService,
    AutomationRunReceipt,
    QueueManualRunCommand,
)

pytestmark = pytest.mark.unit


class FakeCommandRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[AutomationActor, QueueManualRunCommand, str]] = []

    async def queue_manual_run(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
        request_hash: str,
    ) -> AutomationRunReceipt:
        self.calls.append((actor, command, request_hash))
        return AutomationRunReceipt(
            receipt_id="receipt-1",
            operation_id="operation-1",
            run_id="run-1",
            runtime_execution_id="execution-1",
            job_id=command.job_id,
            job_revision=command.expected_revision,
            status="queued",
            duplicate=False,
        )


def _actor() -> AutomationActor:
    return AutomationActor(
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
    )


def _command() -> QueueManualRunCommand:
    return QueueManualRunCommand(
        job_id="job-1",
        expected_revision=7,
        idempotency_key="intent-1",
        conversation_id="conversation-1",
    )


async def test_manual_run_command_is_canonicalized_before_repository_write() -> None:
    repository = FakeCommandRepository()
    service = AutomationCommandService(repository)

    receipt = await service.queue_manual_run(actor=_actor(), command=_command())
    second = await service.queue_manual_run(actor=_actor(), command=_command())

    assert receipt.status == "queued"
    assert second.run_id == receipt.run_id
    assert len(repository.calls) == 2
    assert repository.calls[0][2] == repository.calls[1][2]
    assert len(repository.calls[0][2]) == 64


async def test_manual_run_hash_changes_when_the_user_intent_changes() -> None:
    repository = FakeCommandRepository()
    service = AutomationCommandService(repository)

    await service.queue_manual_run(actor=_actor(), command=_command())
    await service.queue_manual_run(
        actor=_actor(),
        command=replace(_command(), conversation_id="conversation-2"),
    )

    assert repository.calls[0][2] != repository.calls[1][2]


@pytest.mark.parametrize(
    ("actor", "command"),
    [
        (replace(_actor(), tenant_id=""), _command()),
        (replace(_actor(), project_id=" "), _command()),
        (replace(_actor(), user_id=""), _command()),
        (_actor(), replace(_command(), job_id="")),
        (_actor(), replace(_command(), expected_revision=0)),
        (_actor(), replace(_command(), idempotency_key=" ")),
    ],
)
async def test_invalid_manual_run_authority_never_reaches_repository(
    actor: AutomationActor,
    command: QueueManualRunCommand,
) -> None:
    repository = FakeCommandRepository()
    service = AutomationCommandService(repository)

    with pytest.raises(ValueError):
        await service.queue_manual_run(actor=actor, command=command)

    assert repository.calls == []
