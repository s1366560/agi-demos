"""Unit tests for ProjectAgentActor HITL resume paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.persistence import (
    database as database_mod,
    sql_hitl_request_repository as hitl_repo_mod,
)
from src.infrastructure.agent.actor import execution as execution_mod, project_agent_actor
from src.infrastructure.agent.hitl import (
    coordinator as coordinator_mod,
    utils as hitl_utils_mod,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import DataPlaneGenerationAdmissionV2


def _build_actor() -> object:
    actor_cls = project_agent_actor.ProjectAgentActor
    inner_cls = actor_cls.__ray_metadata__.modified_class
    actor = inner_cls.__new__(inner_cls)
    actor._agent = object()
    actor._lease_owner_suffix = "lease-1"
    actor._config = SimpleNamespace(
        tenant_id="tenant-1",
        project_id="project-1",
        agent_mode="plan",
    )
    return actor


@pytest.mark.unit
class TestProjectAgentActor:
    async def test_run_continue_reopens_rejected_live_response(self, monkeypatch) -> None:
        actor = _build_actor()
        reopen_mock = AsyncMock(return_value=True)
        complete_mock = AsyncMock()

        monkeypatch.setattr(actor, "_reopen_answered_request", reopen_mock)
        monkeypatch.setattr(
            coordinator_mod,
            "resolve_by_request_id",
            lambda *_args, **_kwargs: coordinator_mod.ResolveResult.REJECTED,
        )
        monkeypatch.setattr(coordinator_mod, "complete_hitl_request", complete_mock)

        result = await actor._run_continue("req-1", {"answer": "ok"}, "conv-1", "msg-1")

        assert result == {
            "status": "rejected",
            "request_id": "req-1",
            "ack": True,
            "durably_completed": False,
        }
        reopen_mock.assert_awaited_once_with("req-1")
        complete_mock.assert_not_awaited()

    async def test_resume_continue_request_uses_stable_lease_owner(self, monkeypatch) -> None:
        actor = _build_actor()
        repo = SimpleNamespace(claim_for_processing=AsyncMock(return_value=None))
        session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = session
        session_cm.__aexit__.return_value = False

        monkeypatch.setattr(database_mod, "async_session_factory", lambda: session_cm)
        monkeypatch.setattr(hitl_repo_mod, "SqlHITLRequestRepository", lambda _session: repo)

        result = await actor._resume_continue_request(
            request_id="req-1",
            response_data={"answer": "ok"},
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result == {
            "status": "processing",
            "request_id": "req-1",
            "ack": False,
            "durably_completed": False,
        }
        repo.claim_for_processing.assert_awaited_once_with(
            "req-1",
            lease_owner="agent:tenant-1:project-1:plan:lease-1",
        )

    async def test_resume_continue_request_rejects_missing_generation_state(
        self,
        monkeypatch,
    ) -> None:
        actor = _build_actor()
        actor._plugin_admission_v2 = DataPlaneGenerationAdmissionV2(
            builtin_runtime_definitions_v2()
        )
        actor._revert_continue_claim = AsyncMock()
        repo = SimpleNamespace(claim_for_processing=AsyncMock(return_value=object()))
        session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = session
        session_cm.__aexit__.return_value = False
        heartbeat = AsyncMock()
        heartbeat.__aenter__.return_value = None
        heartbeat.__aexit__.return_value = False
        continue_mock = AsyncMock(return_value=SimpleNamespace(hitl_pending=False, is_error=False))

        monkeypatch.setattr(database_mod, "async_session_factory", lambda: session_cm)
        monkeypatch.setattr(hitl_repo_mod, "SqlHITLRequestRepository", lambda _session: repo)
        monkeypatch.setattr(
            hitl_utils_mod, "processing_lease_heartbeat", lambda *_a, **_k: heartbeat
        )
        monkeypatch.setattr(
            execution_mod,
            "load_hitl_state_for_resume",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(project_agent_actor, "continue_project_chat", continue_mock)

        try:
            with pytest.raises(RuntimeV2Error) as error:
                await actor._resume_continue_request(
                    request_id="req-1",
                    response_data={"answer": "ok"},
                    conversation_id="conv-1",
                    message_id="msg-1",
                )
        finally:
            await actor._plugin_admission_v2.close()

        assert error.value.code == "generation_descriptor_missing"
        continue_mock.assert_not_awaited()
        actor._revert_continue_claim.assert_awaited_once_with("req-1")

    async def test_resume_continue_request_admits_persisted_generation(self, monkeypatch) -> None:
        actor = _build_actor()
        repo = SimpleNamespace(claim_for_processing=AsyncMock(return_value=object()))
        session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = session
        session_cm.__aexit__.return_value = False
        generation = {
            "profile_id": "default-v2",
            "generation": 7,
            "digest": "a" * 64,
        }
        state = SimpleNamespace(
            plugin_generation=generation,
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conv-1",
            message_id="msg-1",
            user_id="user-1",
        )
        lease_active = False
        admission_context = AsyncMock()

        async def _enter_admission() -> object:
            nonlocal lease_active
            lease_active = True
            return object()

        async def _exit_admission(*_args: object) -> bool:
            nonlocal lease_active
            lease_active = False
            return False

        admission_context.__aenter__.side_effect = _enter_admission
        admission_context.__aexit__.side_effect = _exit_admission
        admit = MagicMock(return_value=admission_context)
        actor._plugin_admission_v2 = SimpleNamespace(admit=admit)
        heartbeat = AsyncMock()
        heartbeat.__aenter__.return_value = None
        heartbeat.__aexit__.return_value = False

        async def _continue_with_lease(*_args: object, **_kwargs: object) -> object:
            assert lease_active
            return SimpleNamespace(hitl_pending=False, is_error=False)

        continue_mock = AsyncMock(side_effect=_continue_with_lease)

        monkeypatch.setattr(database_mod, "async_session_factory", lambda: session_cm)
        monkeypatch.setattr(hitl_repo_mod, "SqlHITLRequestRepository", lambda _session: repo)
        monkeypatch.setattr(
            hitl_utils_mod, "processing_lease_heartbeat", lambda *_a, **_k: heartbeat
        )
        monkeypatch.setattr(
            execution_mod,
            "load_hitl_state_for_resume",
            AsyncMock(return_value=state),
        )
        monkeypatch.setattr(project_agent_actor, "continue_project_chat", continue_mock)

        result = await actor._resume_continue_request(
            request_id="req-1",
            response_data={"answer": "ok"},
            conversation_id="conv-1",
            message_id="msg-1",
        )

        assert result == {
            "status": "continued",
            "request_id": "req-1",
            "ack": True,
            "durably_completed": True,
        }
        assert admit.call_args.kwargs["descriptor_payload"] == generation
        assert admit.call_args.kwargs["distribution_payload"] is None
        assert admit.call_args.kwargs["operation_id"] == "hitl-resume:req-1"
        continue_mock.assert_awaited_once()
        assert lease_active is False
