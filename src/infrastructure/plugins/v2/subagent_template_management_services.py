"""Generation-owned persistence and application seams for SubAgent templates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.repositories.subagent_repository import SubAgentRepositoryPort
from src.domain.ports.repositories.subagent_template_repository import (
    SubAgentTemplateRepositoryPort,
)
from src.infrastructure.adapters.secondary.persistence.seed_templates import (
    seed_builtin_templates,
)
from src.infrastructure.adapters.secondary.persistence.sql_subagent_template_repository import (
    SqlSubAgentTemplateRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .subagent_management_services import (
    SubAgentAlreadyExistsV2,
    SubAgentNotFoundV2,
    SubAgentProjectAccessProtocolV2,
    SubAgentRepositoryFactoryProtocolV2,
)

SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/subagent-template-repository-provider"
)
SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.subagent-template-repository-provider"
)
SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2 = (
    "builtin://memstack/application/subagent-template-management"
)
SUBAGENT_TEMPLATE_MANAGEMENT_SERVICE_V2 = "service:application.subagent-template-management"
SUBAGENT_TEMPLATE_MANAGEMENT_TEMPLATES_INJECT_V2 = "templates"
SUBAGENT_TEMPLATE_MANAGEMENT_SUBAGENTS_INJECT_V2 = "subagents"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


class SubAgentTemplateManagementErrorV2(RuntimeError):
    """Base failure for the SubAgent template application seam."""


class SubAgentTemplateNotFoundV2(SubAgentTemplateManagementErrorV2):
    """The requested template is absent from the exact tenant authority."""


class SubAgentTemplateAlreadyExistsV2(SubAgentTemplateManagementErrorV2):
    """A template name and version already exist in the exact tenant authority."""


class SubAgentTemplateBuiltinMutationV2(SubAgentTemplateManagementErrorV2):
    """A caller attempted to mutate an immutable builtin template."""


class SubAgentTemplatePersistenceErrorV2(SubAgentTemplateManagementErrorV2):
    """Persistence violated the operation-owned application contract."""


@dataclass(frozen=True, kw_only=True)
class SubAgentTemplatePageV2:
    """One exact-tenant page and its matching total."""

    templates: list[dict[str, Any]]
    total: int


@dataclass(frozen=True, kw_only=True)
class SubAgentTemplateRepositoriesV2:
    """Operation-owned template persistence port."""

    db: AsyncSession
    templates: SubAgentTemplateRepositoryPort


@runtime_checkable
class SubAgentTemplateRepositoryFactoryProtocolV2(Protocol):
    def build(self, operation: OperationContextV2) -> SubAgentTemplateRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSubAgentTemplateRepositoryFactoryV2:
    """Create the SQL template adapter from the operation DB service."""

    strategy: str

    def build(self, operation: OperationContextV2) -> SubAgentTemplateRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "SubAgent template management requires an AsyncSession operation service",
            )
        return SubAgentTemplateRepositoriesV2(
            db=db,
            templates=SqlSubAgentTemplateRepository(db),
        )


@runtime_checkable
class SubAgentTemplateManagementServiceProtocolV2(Protocol):
    tenant_id: str
    user_id: str

    async def list_published(
        self,
        *,
        category: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> SubAgentTemplatePageV2: ...

    async def list_categories(self) -> list[str]: ...

    async def create(self, template: Mapping[str, Any]) -> dict[str, Any]: ...

    async def require_template(self, template_id: str) -> dict[str, Any]: ...

    async def update(
        self,
        template_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    async def delete(self, template_id: str) -> None: ...

    async def install(self, template_id: str) -> SubAgent: ...

    async def export_subagent(self, subagent_id: str) -> dict[str, Any]: ...

    async def seed_builtin(self) -> int: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentTemplateManagementServiceV2:
    """Operation-owned template CRUD, install, export, and seed authority."""

    db: AsyncSession
    templates: SubAgentTemplateRepositoryPort
    subagents: SubAgentRepositoryPort
    project_access: SubAgentProjectAccessProtocolV2
    tenant_id: str
    user_id: str

    async def list_published(
        self,
        *,
        category: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> SubAgentTemplatePageV2:
        templates = await self.templates.list_templates(
            tenant_id=self.tenant_id,
            category=category,
            query=query,
            published_only=True,
            limit=limit,
            offset=offset,
        )
        for template in templates:
            self._ensure_template_tenant(template)
        total = await self.templates.count_templates(
            tenant_id=self.tenant_id,
            category=category,
        )
        return SubAgentTemplatePageV2(templates=templates, total=total)

    async def list_categories(self) -> list[str]:
        return await self.templates.list_categories(self.tenant_id)

    async def create(self, template: Mapping[str, Any]) -> dict[str, Any]:
        template_data = dict(template)
        name = _required_string(template_data, "name")
        version = _required_string(template_data, "version")
        existing = await self.templates.get_by_name(self.tenant_id, name, version)
        if existing is not None:
            raise SubAgentTemplateAlreadyExistsV2(f"{name}@{version}")
        template_data["tenant_id"] = self.tenant_id
        created = await self.templates.create(template_data)
        self._ensure_template_tenant(created)
        await self.db.commit()
        return created

    async def require_template(self, template_id: str) -> dict[str, Any]:
        _require_identifier(template_id, field_name="template_id")
        template = await self.templates.get_by_id(template_id)
        if template is None or template.get("tenant_id") != self.tenant_id:
            raise SubAgentTemplateNotFoundV2(template_id)
        return template

    async def update(
        self,
        template_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        template = await self.require_template(template_id)
        self._ensure_mutable(template)
        update_data = dict(data)
        update_data.pop("tenant_id", None)
        update_data.pop("is_builtin", None)
        updated = await self.templates.update(template_id, update_data)
        if updated is None:
            raise SubAgentTemplatePersistenceErrorV2("template disappeared during update")
        self._ensure_template_identity(template_id, updated)
        await self.db.commit()
        return updated

    async def delete(self, template_id: str) -> None:
        template = await self.require_template(template_id)
        self._ensure_mutable(template)
        deleted = await self.templates.delete(template_id)
        if not deleted:
            raise SubAgentTemplatePersistenceErrorV2("template disappeared during delete")
        await self.db.commit()

    async def install(self, template_id: str) -> SubAgent:
        template = await self.require_template(template_id)
        name = _required_string(template, "name")
        existing = await self.subagents.get_by_name(self.tenant_id, name)
        if existing is not None:
            raise SubAgentAlreadyExistsV2(name)
        model_value = _optional_string(template, "model", default="inherit")
        try:
            model = AgentModel(model_value)
        except ValueError as exc:
            raise SubAgentTemplatePersistenceErrorV2("template model is invalid") from exc
        subagent = SubAgent.create(
            tenant_id=self.tenant_id,
            name=name,
            display_name=_optional_string(template, "display_name", default=name),
            system_prompt=_required_string(template, "system_prompt"),
            trigger_description=_optional_string(
                template,
                "trigger_description",
                default=name,
            ),
            trigger_keywords=_string_list(template, "trigger_keywords"),
            trigger_examples=_string_list(template, "trigger_examples"),
            model=model,
            max_tokens=_integer(template, "max_tokens", default=4096),
            temperature=_number(template, "temperature", default=0.7),
            max_iterations=_integer(template, "max_iterations", default=10),
            allowed_tools=_string_list(template, "allowed_tools", default=["*"]),
        )
        created = await self.subagents.create(subagent)
        if created.tenant_id != self.tenant_id:
            raise SubAgentTemplatePersistenceErrorV2(
                "SubAgent repository returned a cross-tenant record"
            )
        await self.templates.increment_install_count(template_id)
        await self.db.commit()
        return created

    async def export_subagent(self, subagent_id: str) -> dict[str, Any]:
        _require_identifier(subagent_id, field_name="subagent_id")
        subagent = await self.subagents.get_by_id(subagent_id)
        if subagent is None or subagent.tenant_id != self.tenant_id:
            raise SubAgentNotFoundV2(subagent_id)
        if subagent.project_id is not None:
            _ = await self.project_access.require_access(
                project_id=subagent.project_id,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )
        created = await self.templates.create(
            {
                "tenant_id": self.tenant_id,
                "name": subagent.name,
                "display_name": subagent.display_name,
                "description": f"Exported from SubAgent: {subagent.display_name}",
                "category": "custom",
                "system_prompt": subagent.system_prompt,
                "trigger_description": subagent.trigger.description,
                "trigger_keywords": list(subagent.trigger.keywords),
                "trigger_examples": list(subagent.trigger.examples),
                "model": subagent.model.value,
                "max_tokens": subagent.max_tokens,
                "temperature": subagent.temperature,
                "max_iterations": subagent.max_iterations,
                "allowed_tools": list(subagent.allowed_tools),
                "is_published": True,
            }
        )
        self._ensure_template_tenant(created)
        await self.db.commit()
        return created

    async def seed_builtin(self) -> int:
        created = await seed_builtin_templates(self.templates, self.tenant_id)
        await self.db.commit()
        return created

    def _ensure_template_tenant(self, template: Mapping[str, Any]) -> None:
        if template.get("tenant_id") != self.tenant_id:
            raise SubAgentTemplateNotFoundV2(str(template.get("id", "unknown")))

    def _ensure_template_identity(
        self,
        template_id: str,
        template: Mapping[str, Any],
    ) -> None:
        self._ensure_template_tenant(template)
        if template.get("id") != template_id:
            raise SubAgentTemplatePersistenceErrorV2(
                "template repository returned a different record"
            )

    @staticmethod
    def _ensure_mutable(template: Mapping[str, Any]) -> None:
        if template.get("is_builtin") is True:
            raise SubAgentTemplateBuiltinMutationV2(str(template.get("id", "unknown")))


@runtime_checkable
class SubAgentTemplateManagementResolverProtocolV2(Protocol):
    def resolve(
        self,
        operation: OperationContextV2,
    ) -> SubAgentTemplateManagementServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentTemplateManagementResolverV2:
    templates: SubAgentTemplateRepositoryFactoryProtocolV2
    subagents: SubAgentRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SubAgentTemplateManagementServiceV2:
        scope = operation.context.scope
        if scope.kind is not ScopeKindV2.TENANT or scope.tenant_id is None:
            raise RuntimeV2Error(
                "invalid_subagent_template_operation_scope",
                "SubAgent template management requires an exact tenant operation scope",
            )
        identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
        if not isinstance(identity, Mapping):
            raise RuntimeV2Error(
                "invalid_subagent_template_operation_identity",
                "SubAgent template management requires a structured operation identity",
            )
        identity_mapping = cast("Mapping[str, object]", identity)
        tenant_id = identity_mapping.get("tenant_id")
        user_id = identity_mapping.get("user_id")
        if (
            not isinstance(tenant_id, str)
            or tenant_id != scope.tenant_id
            or not isinstance(user_id, str)
            or not user_id.strip()
        ):
            raise RuntimeV2Error(
                "invalid_subagent_template_operation_identity",
                "SubAgent template identity does not match the operation scope",
            )
        template_repositories = self.templates.build(operation)
        subagent_repositories = self.subagents.build(operation)
        if template_repositories.db is not subagent_repositories.db:
            raise RuntimeV2Error(
                "subagent_template_transaction_mismatch",
                "SubAgent template repositories must share one operation DB session",
            )
        return SubAgentTemplateManagementServiceV2(
            db=template_repositories.db,
            templates=template_repositories.templates,
            subagents=subagent_repositories.subagents,
            project_access=subagent_repositories.project_access,
            tenant_id=scope.tenant_id,
            user_id=user_id,
        )


def _apply_subagent_template_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "SubAgent template repository Provider requires strategy request-async-session"
        )
    _ = context.provide(
        SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlSubAgentTemplateRepositoryFactoryV2(strategy=strategy),
        label="subagent-template-repository-provider",
    )


def _apply_subagent_template_management_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("SubAgent template management requires strategy operation-scoped-provider")
    templates = context.require(SUBAGENT_TEMPLATE_MANAGEMENT_TEMPLATES_INJECT_V2)
    if not isinstance(templates, SubAgentTemplateRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_template_repository_provider",
            "SubAgent template repository Provider has an invalid implementation",
        )
    subagents = context.require(SUBAGENT_TEMPLATE_MANAGEMENT_SUBAGENTS_INJECT_V2)
    if not isinstance(subagents, SubAgentRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_repository_provider",
            "SubAgent repository Provider has an invalid implementation",
        )
    _ = context.provide(
        SUBAGENT_TEMPLATE_MANAGEMENT_SERVICE_V2,
        SubAgentTemplateManagementResolverV2(
            templates=templates,
            subagents=subagents,
        ),
        label="subagent-template-management",
    )


def subagent_template_management_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the template repository Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_subagent_template_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2),
            apply=_apply_subagent_template_management_v2,
        ),
    )


def _required_string(template: Mapping[str, Any], field_name: str) -> str:
    value = template.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    return value


def _optional_string(
    template: Mapping[str, Any],
    field_name: str,
    *,
    default: str,
) -> str:
    value = template.get(field_name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    return value or default


def _string_list(
    template: Mapping[str, Any],
    field_name: str,
    *,
    default: list[str] | None = None,
) -> list[str]:
    value = template.get(field_name)
    if value is None:
        return list(default or [])
    if not isinstance(value, list):
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    items = cast("list[object]", value)
    if not all(isinstance(item, str) for item in items):
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    return [item for item in items if isinstance(item, str)]


def _integer(template: Mapping[str, Any], field_name: str, *, default: int) -> int:
    value = template.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    return int(value)


def _number(template: Mapping[str, Any], field_name: str, *, default: float) -> float:
    value = template.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubAgentTemplatePersistenceErrorV2(f"template {field_name} is invalid")
    return float(value)


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


__all__ = [
    "SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2",
    "SUBAGENT_TEMPLATE_MANAGEMENT_SERVICE_V2",
    "SUBAGENT_TEMPLATE_MANAGEMENT_SUBAGENTS_INJECT_V2",
    "SUBAGENT_TEMPLATE_MANAGEMENT_TEMPLATES_INJECT_V2",
    "SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_MODULE_V2",
    "SUBAGENT_TEMPLATE_REPOSITORY_PROVIDER_SERVICE_V2",
    "SqlSubAgentTemplateRepositoryFactoryV2",
    "SubAgentTemplateAlreadyExistsV2",
    "SubAgentTemplateBuiltinMutationV2",
    "SubAgentTemplateManagementErrorV2",
    "SubAgentTemplateManagementResolverProtocolV2",
    "SubAgentTemplateManagementResolverV2",
    "SubAgentTemplateManagementServiceProtocolV2",
    "SubAgentTemplateManagementServiceV2",
    "SubAgentTemplateNotFoundV2",
    "SubAgentTemplatePageV2",
    "SubAgentTemplatePersistenceErrorV2",
    "SubAgentTemplateRepositoriesV2",
    "SubAgentTemplateRepositoryFactoryProtocolV2",
    "subagent_template_management_definitions_v2",
]
