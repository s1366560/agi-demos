"""Composer commands. Preference shaping stays in the guest."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from plugins.business.agent.backend.chat_operations import (
    ConversationInput,
    _canonical,
    _Input,
    _own_conversation,
)
from plugins.business.agent.guest.binding import (
    CommandContext,
    CommandError,
    Progress,
    bound,
    current,
)


class LlmOverrides(_Input):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)


class SavePreference(ConversationInput):
    llm_overrides: LlmOverrides | None = None
    approval_mode: Literal["ask", "auto_edit", "full_access"] | None = None
    reasoning_effort: Literal["default", "low", "medium", "high"] | None = None
    llm_model_override: str | None = Field(default=None, min_length=1, max_length=512)
    mode: Literal["plan", "build"] | None = None

    @model_validator(mode="after")
    def one_preference(self) -> Self:
        fields = self.model_fields_set - {"conversation_id"}
        if len(fields) != 1:
            raise ValueError("Exactly one composer preference is required")
        field = next(iter(fields))
        if field != "llm_model_override" and getattr(self, field) is None:
            raise ValueError("This preference requires a value")
        return self


def _settings(row: dict[str, Any], mode: str) -> dict[str, Any]:
    config = row.get("agent_config") or {}
    return {
        "approval_mode": config.get("approval_mode") or "ask",
        "reasoning_effort": (config.get("llm_overrides") or {}).get("reasoning_effort")
        or "default",
        "llm_overrides": {
            key: value
            for key, value in (config.get("llm_overrides") or {}).items()
            if key in LlmOverrides.model_fields
        },
        "llm_model_override": config.get("llm_model_override"),
        "mode": mode,
    }


async def voice_conversation_tenant(
    db: object,
    *,
    user_id: str,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
) -> str | None:
    from typing import cast

    from src.host.operations.voice_scope import voice_conversation_tenant as real

    return await real(
        cast("Any", db),
        user_id=user_id,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )


def voice_ticket(*, principal: str, tenant: str, project: str, conversation: str) -> str:
    from src.host.operations.package_voice_lease import voice_ticket as real

    return real(principal=principal, tenant=tenant, project=project, conversation=conversation)


async def authorize_voice(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, str]:
    data = ConversationInput.model_validate(payload)
    if bound():
        return await current().voice(data.conversation_id)
    session = getattr(ctx, "db", None)
    project_id = ctx.scope.project_id
    if not isinstance(project_id, str):
        raise CommandError("forbidden", "Voice requires an accessible cloud conversation")
    tenant = await voice_conversation_tenant(
        session,
        user_id=str(ctx.user.id),
        tenant_id=ctx.scope.tenant_id,
        project_id=project_id,
        conversation_id=data.conversation_id,
    )
    if not tenant:
        raise CommandError("forbidden", "Voice requires an accessible cloud conversation")
    return {
        "conversation_id": data.conversation_id,
        "principal_id": str(ctx.user.id),
        "ticket": voice_ticket(
            principal=str(ctx.user.id),
            tenant=tenant,
            project=project_id,
            conversation=data.conversation_id,
        ),
    }


async def read(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    data = ConversationInput.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    row = await _canonical(ctx, "GET", f"conversations/{data.conversation_id}")
    mode = await _canonical(ctx, "GET", f"plan/mode/{data.conversation_id}")
    return _settings(row, mode["mode"])


async def _routes(_ctx: CommandContext | None = None) -> tuple[str | None, dict[str, str]]:
    roster = await current().model_routes()
    return roster["default_model"], roster["models"]


async def save(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    data = SavePreference.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    path = f"conversations/{data.conversation_id}"
    row = await _canonical(ctx, "GET", path)
    if (
        row.get("execution_target") == "local"
        or (row.get("metadata") or {}).get("execution_target") == "local"
    ):
        raise CommandError("forbidden", "Device conversations only support Web replay")
    if data.mode is not None:
        mode = await _canonical(
            ctx,
            "POST",
            "plan/mode",
            body={"conversation_id": data.conversation_id, "mode": data.mode},
        )
        return _settings(row, mode["mode"])
    change: dict[str, object]
    if data.llm_overrides is not None:
        original = (row.get("agent_config") or {}).get("llm_overrides") or {}
        keep = {
            key: value for key, value in original.items() if key not in LlmOverrides.model_fields
        }
        change = {"llm_overrides": {**keep, **data.llm_overrides.model_dump(exclude_none=True)}}
    elif data.reasoning_effort is not None:
        overrides = dict((row.get("agent_config") or {}).get("llm_overrides") or {})
        if data.reasoning_effort == "default":
            overrides.pop("reasoning_effort", None)
        else:
            overrides["reasoning_effort"] = data.reasoning_effort
        change = {"llm_overrides": overrides}
    elif data.approval_mode is not None:
        change = {"approval_mode": data.approval_mode}
    else:
        model = data.llm_model_override
        change = {"llm_model_override": model}
        if model not in (None, "auto"):
            _, routes = await _routes()
            if model not in routes:
                raise CommandError("forbidden", "Model unavailable for this tenant")
            change["llm_route_override"] = {"provider_id": routes[model], "model_id": model}
    row = await _canonical(ctx, "PATCH", path + "/config", body=change)
    mode = await _canonical(ctx, "GET", f"plan/mode/{data.conversation_id}")
    return _settings(row, mode["mode"])


class Welcome(_Input):
    complete: Literal[True] | None = None


async def welcome(_ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    preference = Welcome.model_validate(payload)
    return await current().welcome(preference.complete)


async def models(_ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    _Input.model_validate(payload)
    default, routes = await _routes()
    return {"default_model": default, "models": sorted(routes)}


COMPOSER_OPERATIONS: dict[str, Any] = {}
