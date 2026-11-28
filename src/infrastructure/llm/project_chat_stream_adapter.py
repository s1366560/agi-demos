"""Apply an authorized project's signed compute-only adapter to a cloud Agent model stream."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, exists, or_, select

from src.domain.llm_providers.models import provider_revision
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel as Catalog,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation as Installation,
    ProjectPluginRelease as Release,
)
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

if TYPE_CHECKING:
    from src.domain.llm_providers.models import ProviderConfig
    from src.host.packages.project_plugin_installation import AgentPackagePin
    from src.infrastructure.agent.core.project_package_tools import ProjectPackageCapabilities


@dataclass(frozen=True)
class ChatStreamAuthority:
    catalog: ProjectPackageCapabilities
    pin: AgentPackagePin
    user_id: str
    provider_id: UUID
    provider_revision: datetime

    async def authorize(self) -> None:
        # One indexed existence query covers live package withdrawal and project/tenant membership.
        pin = self.pin
        self.catalog.check_scope(pin.tenant_id, pin.project_id)
        if self.catalog.actor_id() != self.user_id:
            raise RuntimeV2Error("chat_adapter_forbidden", "Project chat adapter actor changed")
        withdrawn = exists().where(
            Catalog.plugin_id == pin.plugin_id,
            Catalog.version == pin.version,
            or_(Catalog.revoked.is_(True), Catalog.security_scan_status == "failed"),
        )
        member = exists().where(
            UserTenant.user_id == User.id, UserTenant.tenant_id == pin.tenant_id
        )
        # Some pooled clients carry the global "default" label even for mapped providers.
        # Consult the stored mapping and the selected revision, independently of that label.
        mappings = select(TenantProviderMapping.id).where(
            TenantProviderMapping.provider_id == self.provider_id,
            TenantProviderMapping.operation_type == "llm",
        )
        provider = and_(
            LLMProvider.operation_type == "llm",
            LLMProvider.is_active.is_(True),
            LLMProvider.is_enabled.is_(True),
            or_(
                and_(~mappings.exists(), LLMProvider.is_default.is_(True)),
                mappings.where(TenantProviderMapping.tenant_id == pin.tenant_id).exists(),
            ),
        )
        allowed = (
            select(LLMProvider.updated_at)
            .select_from(User)
            .join(LLMProvider, LLMProvider.id == self.provider_id)
            .join(UserProject, UserProject.user_id == User.id)
            .join(Project, Project.id == UserProject.project_id)
            .join(Installation, Installation.project_id == Project.id)
            .join(
                Release,
                and_(
                    Release.project_id == Project.id,
                    Release.tenant_id == Project.tenant_id,
                    Release.plugin_id == Installation.plugin_id,
                ),
            )
            .where(
                User.id == self.user_id,
                User.is_active.is_(True),
                Project.id == pin.project_id,
                Project.tenant_id == pin.tenant_id,
                UserProject.role.in_(("member", "admin", "owner")),
                or_(User.is_superuser.is_(True), member),
                Installation.plugin_id == pin.plugin_id,
                Installation.enabled.is_(True),
                Installation.active.is_not(None),
                Installation.authorization_epoch == pin.authorization_epoch,
                Release.version == pin.version,
                Release.digest == pin.digest,
                ~withdrawn,
                provider,
            )
        )
        async with self.catalog.sessions() as db:
            stamp = await db.scalar(allowed)
            if stamp is None or provider_revision(stamp) != provider_revision(
                self.provider_revision
            ):
                raise RuntimeV2Error(
                    "chat_adapter_forbidden", "Project chat adapter authorization has ended"
                )


@dataclass(frozen=True)
class ChatStreamAdapter:
    authority: ChatStreamAuthority
    publish_reasoning: bool

    def filter_chunk(self, chunk: object) -> None:
        # Only explicit reasoning deltas participate. Content, tool calls, usage and finish status
        # retain the provider's stream semantics. The Wasm guest never receives response text.
        if not self.publish_reasoning:
            for choice in getattr(chunk, "choices", ()) or ():
                delta = getattr(choice, "delta", None)
                for name in ("reasoning_content", "thinking", "reasoning"):
                    if getattr(delta, name, None) is not None:
                        setattr(delta, name, None)


def any_pinned_chat_adapter() -> bool:
    from src.infrastructure.agent.core.project_package_tools import current_package_capabilities

    catalog = current_package_capabilities()
    return catalog is not None and any(pin.chat_adapter for pin in catalog.pins)


def selected_chat_adapter(
    provider: str,
) -> tuple[ProjectPackageCapabilities, AgentPackagePin] | None:
    from src.infrastructure.agent.core.project_package_tools import current_package_capabilities

    catalog = current_package_capabilities()
    if catalog is None:
        return None
    if provider == "custom_openai":
        provider = "openai"
    pins = [
        pin for pin in catalog.pins if pin.chat_adapter and pin.chat_provider in {None, provider}
    ]
    if len(pins) > 1:
        raise RuntimeV2Error(
            "chat_adapter_conflict", "Multiple chat adapters are pinned to the same run"
        )
    return (catalog, pins[0]) if pins else None


async def adapt_project_chat_request(
    provider: ProviderConfig, kwargs: dict[str, Any]
) -> ChatStreamAdapter | None:
    selected = selected_chat_adapter(provider.provider_type.value)
    if selected is None:
        return None
    from src.host.packages.project_plugin_installation import (
        ProjectPluginInstallationService,
    )
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

    catalog, pin = selected
    catalog.check_scope(pin.tenant_id, pin.project_id)
    transport = provider.provider_type.value
    if provider.tenant_id not in {None, "default", pin.tenant_id} or transport not in {
        "openai",
        "deepseek",
    }:
        raise RuntimeV2Error(
            "chat_adapter_transport", "Project chat adapter cannot use this provider"
        )
    import litellm

    _, actual_transport, _, _ = litellm.get_llm_provider(
        model=kwargs["model"],
        custom_llm_provider=kwargs.get("custom_llm_provider"),
        api_base=kwargs.get("api_base"),
        api_key=kwargs.get("api_key"),
    )
    if actual_transport != transport and not (
        transport == "openai" and actual_transport == "custom_openai"
    ):
        raise RuntimeV2Error(
            "chat_adapter_transport", "Configured chat provider differs from the selected transport"
        )
    actor = catalog.actor_id()
    field = "max_completion_tokens" if "max_completion_tokens" in kwargs else "max_tokens"
    budget = kwargs[field]
    if type(budget) is not int or budget < 1:
        raise RuntimeV2Error("chat_adapter_input", "Host token budget must be positive")
    tools = bool(kwargs.get("tools"))
    authority = ChatStreamAuthority(catalog, pin, actor, provider.id, provider.updated_at)
    await authority.authorize()
    facts = {"provider": transport, "token_limit": budget, "has_tools": tools}
    async with catalog.sessions() as db:
        service = ProjectPluginInstallationService(
            db, catalog.scope, catalog.keys, actor_id=actor, run_id=catalog.run_id
        )
        try:
            result = await service.invoke_pinned_tool(
                pin, "adapt_chat", facts, run_pins=catalog.pins
            )
        except (OptionalBusinessError, ValueError) as exc:
            raise RuntimeV2Error(
                "chat_adapter_unavailable", "Pinned project chat adapter is unavailable"
            ) from exc
    limit, publish = result.get("token_limit"), result.get("publish_reasoning")
    if (
        result.keys() != {"token_limit", "publish_reasoning"}
        or type(limit) is not int
        or not 1 <= limit <= budget
        or type(publish) is not bool
        or (transport == "deepseek" and tools and not publish)
    ):
        raise RuntimeV2Error(
            "chat_adapter_output", "Chat adapter returned unsupported transport options"
        )
    kwargs[field] = limit
    return ChatStreamAdapter(authority, publish)
