"""Generation admission tests for persisted HITL crash recovery."""

from contextlib import asynccontextmanager
from typing import Any, ClassVar

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.agent.hitl.state_store import HITLAgentState
from src.infrastructure.plugins.v2 import runtime_host as runtime_host_mod
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _state(
    *,
    descriptor: dict[str, str | int] | None = None,
    distribution: dict[str, Any] | None = None,
) -> HITLAgentState:
    return HITLAgentState(
        conversation_id="conversation-state",
        message_id="message-state",
        tenant_id="tenant-state",
        project_id="project-state",
        user_id="user-state",
        hitl_request_id="request-state",
        hitl_type="clarification",
        hitl_request_data={"question": "Continue?"},
        plugin_generation=descriptor,
        plugin_distribution=distribution,
    )


class _RecordingAdmission:
    instances: ClassVar[list["_RecordingAdmission"]] = []

    def __init__(self, _definitions: object) -> None:
        self.admit_kwargs: dict[str, Any] | None = None
        self.active = False
        self.closed = False
        self.instances.append(self)

    @asynccontextmanager
    async def admit(self, **kwargs: Any):
        self.admit_kwargs = kwargs
        self.active = True
        try:
            yield object()
        finally:
            self.active = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_recording_admissions() -> None:
    _RecordingAdmission.instances.clear()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admission_requires_persisted_generation_descriptor() -> None:
    from src.infrastructure.agent.hitl.generation_recovery_v2 import (
        admit_persisted_hitl_state_v2,
    )

    with pytest.raises(RuntimeV2Error) as error:
        async with admit_persisted_hitl_state_v2(_state(), request_id="request-state"):
            pass

    assert error.value.code == "generation_descriptor_missing"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admission_requires_complete_persisted_distribution() -> None:
    from src.infrastructure.agent.hitl.generation_recovery_v2 import (
        admit_persisted_hitl_state_v2,
    )

    descriptor = {
        "profile_id": "default-v2",
        "generation": 3,
        "digest": "c" * 64,
    }
    with pytest.raises(RuntimeV2Error) as error:
        async with admit_persisted_hitl_state_v2(
            _state(descriptor=descriptor),
            request_id="request-state",
        ):
            pass

    assert error.value.code == "generation_distribution_missing"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admission_uses_snapshot_scope_identity_and_metadata_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.hitl.generation_recovery_v2 import (
        admit_persisted_hitl_state_v2,
    )

    descriptor = {
        "profile_id": "default-v2",
        "generation": 4,
        "digest": "d" * 64,
    }
    distribution = {
        "descriptor": descriptor,
        "snapshot": {"profile_id": "default-v2", "generation": 4},
        "envelope": {"version": 8, "nonce": "publication-8"},
    }
    monkeypatch.setattr(
        runtime_host_mod,
        "DataPlaneGenerationAdmissionV2",
        _RecordingAdmission,
    )

    async with admit_persisted_hitl_state_v2(
        _state(descriptor=descriptor, distribution=distribution),
        request_id="request-state",
    ):
        admission = _RecordingAdmission.instances[-1]
        assert admission.active is True

    admission = _RecordingAdmission.instances[-1]
    assert admission.closed is True
    assert admission.admit_kwargs is not None
    assert admission.admit_kwargs["descriptor_payload"] == descriptor
    assert admission.admit_kwargs["distribution_payload"] == distribution
    scope = admission.admit_kwargs["scope"]
    assert scope.kind is ScopeKindV2.SESSION
    assert scope.tenant_id == "tenant-state"
    assert scope.project_id == "project-state"
    assert scope.session_id == "conversation-state"
    services = admission.admit_kwargs["services"]
    assert services[OPERATION_IDENTITY_SERVICE_V2] == {
        "tenant_id": "tenant-state",
        "user_id": "user-state",
    }
    assert services[OPERATION_METADATA_SERVICE_V2] == {
        "kind": "hitl-resume",
        "request_id": "request-state",
        "message_id": "message-state",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admission_closes_when_recovery_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.hitl.generation_recovery_v2 import (
        admit_persisted_hitl_state_v2,
    )

    descriptor = {
        "profile_id": "default-v2",
        "generation": 5,
        "digest": "e" * 64,
    }
    distribution = {
        "descriptor": descriptor,
        "snapshot": {"profile_id": "default-v2", "generation": 5},
        "envelope": {"version": 9, "nonce": "publication-9"},
    }
    monkeypatch.setattr(
        runtime_host_mod,
        "DataPlaneGenerationAdmissionV2",
        _RecordingAdmission,
    )

    with pytest.raises(RuntimeError, match="initialize failed"):
        async with admit_persisted_hitl_state_v2(
            _state(descriptor=descriptor, distribution=distribution),
            request_id="request-state",
        ):
            raise RuntimeError("initialize failed")

    admission = _RecordingAdmission.instances[-1]
    assert admission.active is False
    assert admission.closed is True
