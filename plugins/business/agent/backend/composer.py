"""Scoped presentation and mutation of preferences exposed by the original Web composer."""

from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import Field, model_validator
from sqlalchemy import select

from src.host.operations.package_voice_lease import voice_ticket
from src.host.operations.voice_scope import voice_conversation_tenant
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.persistence.tenant_model_roster import (
    selectable_provider_models,
    tenant_chat_providers,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_operations import (
    ConversationInput,
    _canonical,
    _Input,
    _own_conversation,
)
from .composer_context import project_context
from .lifecycle_control import control

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


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


async def _routes(ctx: "PackageOperationContext") -> tuple[str | None, dict[str, str]]:
    providers = list(await ctx.db.scalars(tenant_chat_providers(ctx.scope.tenant_id)))
    routes: dict[str, str] = {}
    default = None
    for provider in providers:
        offered = selectable_provider_models(provider)
        if default is None and provider.llm_model in offered:
            default = provider.llm_model
        for model in offered:
            routes.setdefault(model, str(provider.id))
    return default, routes


async def models(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    _Input.model_validate(payload)
    default, routes = await _routes(ctx)
    return {"default_model": default, "models": sorted(routes)}


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


async def authorize_voice(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, str]:
    data = ConversationInput.model_validate(payload)
    tenant = await voice_conversation_tenant(
        ctx.db,
        user_id=str(ctx.user.id),
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        conversation_id=data.conversation_id,
    )
    if not tenant:
        raise OptionalBusinessError("forbidden", "Voice requires an accessible cloud conversation")
    return {
        "conversation_id": data.conversation_id,
        "principal_id": str(ctx.user.id),
        "ticket": voice_ticket(
            principal=str(ctx.user.id),
            tenant=tenant,
            project=ctx.scope.project_id,
            conversation=data.conversation_id,
        ),
    }


async def read(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    data = ConversationInput.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    row = await _canonical(ctx, "GET", f"conversations/{data.conversation_id}")
    mode = await _canonical(ctx, "GET", f"plan/mode/{data.conversation_id}")
    return _settings(row, mode["mode"])


async def save(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    data = SavePreference.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    path = f"conversations/{data.conversation_id}"
    row = await _canonical(ctx, "GET", path)
    if (
        row.get("execution_target") == "local"
        or (row.get("metadata") or {}).get("execution_target") == "local"
    ):
        raise OptionalBusinessError("forbidden", "Device conversations only support Web replay")
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
            _, routes = await _routes(ctx)
            if model not in routes:
                raise OptionalBusinessError("forbidden", "Model unavailable for this tenant")
            change["llm_route_override"] = {"provider_id": routes[model], "model_id": model}
    row = await _canonical(ctx, "PATCH", path + "/config", body=change)
    mode = await _canonical(ctx, "GET", f"plan/mode/{data.conversation_id}")
    return _settings(row, mode["mode"])


class Welcome(_Input):
    complete: Literal[True] | None = None


async def welcome(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    preference = Welcome.model_validate(payload)
    field = "memstack_agent_web_onboarding_complete"
    if preference.complete is None:
        profile = await ctx.db.scalar(select(User.profile).where(User.id == ctx.user.id))
        return {"complete": (profile or {}).get(field) is True}
    user = await ctx.db.scalar(
        select(User)
        .where(User.id == ctx.user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise OptionalBusinessError("forbidden", "User unavailable")
    if (user.profile or {}).get(field) is not True:
        user.profile = {**(user.profile or {}), field: True}
    await ctx.db.commit()
    return {"complete": True}


COMPOSER_OPERATIONS = {
    "app.agent.lifecycle.control": control,
    "app.agent.voice.authorize": authorize_voice,
    "app.agent.composer.welcome": welcome,
    "app.agent.composer.read": read,
    "app.agent.composer.save": save,
    "app.agent.composer.models": models,
    "app.agent.composer.context": project_context,
}
