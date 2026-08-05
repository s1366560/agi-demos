"""Authorized, revision-bound WebSocket control commands for active SubAgents."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import exists, select

from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    Conversation,
    UserProject,
    UserTenant,
)
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel

_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
_ACTIVE_SUBAGENT_STATUSES = frozenset({"pending", "running"})
_RECEIPT_TTL_SECONDS = 86_400


class _ControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["kill_run", "steer"]
    conversation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    expected_run_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)


class _KillRunCommand(_ControlCommand):
    type: Literal["kill_run"]
    cascade: bool = False


class _SteerCommand(_ControlCommand):
    type: Literal["steer"]
    instruction: str = Field(min_length=1)

    @field_validator("instruction")
    @classmethod
    def _instruction_must_contain_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must contain non-whitespace content")
        return value


def _payload_hash(command: _ControlCommand) -> str:
    encoded = json.dumps(
        command.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _receipt_key(user_id: str, idempotency_key: str) -> str:
    return f"agent:control:receipt:{user_id}:{idempotency_key}"


def _decode_json(raw: Any) -> dict[str, Any] | None:  # noqa: ANN401
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else raw
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


class _SubAgentControlHandler(WebSocketMessageHandler):
    command_type: Literal["kill_run", "steer"]

    @property
    def message_type(self) -> str:
        return self.command_type

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        command = self._validate(message)
        if command is None:
            await self._reject(context, message, "invalid_control_command")
            return

        conversation_result = await context.db.execute(
            refresh_select_statement(
                select(Conversation).where(
                    Conversation.id == command.conversation_id,
                    Conversation.user_id == context.user_id,
                    Conversation.tenant_id == context.tenant_id,
                    exists(
                        select(UserProject.id).where(
                            UserProject.project_id == Conversation.project_id,
                            UserProject.user_id == context.user_id,
                        )
                    ),
                    exists(
                        select(UserTenant.id).where(
                            UserTenant.tenant_id == Conversation.tenant_id,
                            UserTenant.user_id == context.user_id,
                        )
                    ),
                )
            )
        )
        conversation = conversation_result.scalar_one_or_none()
        if conversation is None:
            await self._reject(context, message, "control_scope_denied")
            return

        await self._handle_scoped_command(context, message, command, conversation)

    async def _handle_scoped_command(
        self,
        context: MessageContext,
        message: dict[str, Any],
        command: _ControlCommand,
        conversation: Conversation,
    ) -> None:
        """Validate mutable run/SubAgent authority after conversation scope is established."""

        run_result = await context.db.execute(
            refresh_select_statement(
                select(AgentPlanRunModel)
                .where(
                    AgentPlanRunModel.conversation_id == conversation.id,
                    AgentPlanRunModel.project_id == conversation.project_id,
                    AgentPlanRunModel.status.in_(_ACTIVE_RUN_STATUSES),
                )
                .order_by(AgentPlanRunModel.created_at.desc(), AgentPlanRunModel.id.desc())
                .limit(1)
            )
        )
        parent_run = run_result.scalar_one_or_none()
        if parent_run is None:
            await self._reject(context, message, "no_active_run", project_id=conversation.project_id)
            return
        if parent_run.revision != command.expected_run_revision:
            await self._reject(
                context,
                message,
                "run_revision_conflict",
                project_id=conversation.project_id,
                authority_revision=parent_run.revision,
            )
            return
        if self.command_type == "steer" and parent_run.status != "running":
            await self._reject(
                context,
                message,
                "control_action_not_allowed",
                project_id=conversation.project_id,
                authority_revision=parent_run.revision,
            )
            return

        redis = context.container.redis_client
        if redis is None:
            await self._reject(context, message, "control_authority_unavailable")
            return
        state = _decode_json(
            await redis.get(f"subagent:state:{conversation.id}:{command.run_id}")
        )
        if not self._state_is_authorized(state, command, conversation):
            await self._reject(
                context,
                message,
                "subagent_control_denied",
                project_id=conversation.project_id,
                authority_revision=parent_run.revision,
            )
            return

        assert state is not None
        await self._dispatch(
            context,
            command,
            state,
            project_id=conversation.project_id,
            authority_revision=parent_run.revision,
        )

    def _validate(self, message: dict[str, Any]) -> _ControlCommand | None:
        try:
            if self.command_type == "kill_run":
                return _KillRunCommand.model_validate(message)
            return _SteerCommand.model_validate(message)
        except ValidationError:
            return None

    def _state_is_authorized(
        self,
        state: dict[str, Any] | None,
        command: _ControlCommand,
        conversation: Conversation,
    ) -> bool:
        if state is None:
            return False
        return bool(
            state.get("execution_id") == command.run_id
            and state.get("conversation_id") == conversation.id
            and state.get("status") in _ACTIVE_SUBAGENT_STATUSES
            and state.get("subagent_id") in (conversation.participant_agents or [])
        )

    async def _dispatch(
        self,
        context: MessageContext,
        command: _ControlCommand,
        state: dict[str, Any],
        *,
        project_id: str,
        authority_revision: int,
    ) -> None:
        redis = context.container.redis_client
        assert redis is not None
        key = _receipt_key(context.user_id, command.idempotency_key)
        digest = _payload_hash(command)
        existing = _decode_json(await redis.get(key))
        if existing is not None:
            if existing.get("payload_hash") != digest:
                await self._reject(context, command.model_dump(), "idempotency_conflict")
                return
            receipt = existing.get("receipt")
            if isinstance(receipt, dict):
                await context.send_json({**receipt, "duplicate": True})
                return
            await self._reject(context, command.model_dump(), "control_dispatch_in_progress")
            return

        claimed = await redis.set(
            key,
            json.dumps({"payload_hash": digest, "status": "dispatching"}),
            ex=_RECEIPT_TTL_SECONDS,
            nx=True,
        )
        if not claimed:
            await self._reject(context, command.model_dump(), "control_dispatch_in_progress")
            return

        instruction = command.instruction if isinstance(command, _SteerCommand) else ""
        cascade = command.cascade if isinstance(command, _KillRunCommand) else False
        control = ControlMessage(
            run_id=command.run_id,
            message_type=(
                ControlMessageType.KILL
                if self.command_type == "kill_run"
                else ControlMessageType.STEER
            ),
            payload=instruction or "Killed by user",
            sender_id=context.user_id,
            cascade=cascade,
            run_revision=authority_revision,
            idempotency_key=command.idempotency_key,
            target_agent_id=str(state["subagent_id"]),
            target_agent_name=str(state.get("subagent_name") or state["subagent_id"]),
        )
        accepted = await RedisControlChannel(redis).send_control(control)
        if not accepted:
            await redis.delete(key)
            await self._reject(context, command.model_dump(), "control_dispatch_failed")
            return

        receipt = {
            "type": "control_command_ack",
            "action": self.command_type,
            "accepted": True,
            "duplicate": False,
            "reason_code": None,
            "conversation_id": command.conversation_id,
            "project_id": project_id,
            "run_id": command.run_id,
            "run_revision": authority_revision,
            "idempotency_key": command.idempotency_key,
            "cascade": cascade,
        }
        await redis.set(
            key,
            json.dumps({"payload_hash": digest, "status": "accepted", "receipt": receipt}),
            ex=_RECEIPT_TTL_SECONDS,
        )
        await context.send_json(receipt)

    async def _reject(
        self,
        context: MessageContext,
        message: dict[str, Any],
        reason_code: str,
        *,
        project_id: str | None = None,
        authority_revision: int | None = None,
    ) -> None:
        await context.send_json(
            {
                "type": "control_command_ack",
                "action": self.command_type,
                "accepted": False,
                "duplicate": False,
                "reason_code": reason_code,
                "conversation_id": message.get("conversation_id"),
                "project_id": project_id,
                "run_id": message.get("run_id"),
                "run_revision": authority_revision,
                "idempotency_key": message.get("idempotency_key"),
            }
        )


class KillRunHandler(_SubAgentControlHandler):
    """Validate and enqueue a revision-bound SubAgent kill command."""

    command_type: Literal["kill_run", "steer"] = "kill_run"


class SteerSubAgentHandler(_SubAgentControlHandler):
    """Validate and enqueue a revision-bound SubAgent steer command."""

    command_type: Literal["kill_run", "steer"] = "steer"
