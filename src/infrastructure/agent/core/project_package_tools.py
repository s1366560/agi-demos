"""Bind signed project-package tools and progressive Skill instructions to a canonical run."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from plugins.business.agent.engine.processor import ToolDefinition
from src.configuration.config import get_settings
from src.domain.model.agent.skill import Skill, SkillScope, SkillSource
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import (
    AgentPackagePin,
    ProjectPluginInstallationService,
)
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.core.project_package_subagents import (
    SignedProjectSubAgent,
    package_model_name,
    signed_subagent,
)
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    contribute_operation_tool_definitions_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    current_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime_context import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.infrastructure.plugins.v2.runtime import OperationContextV2
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import SignedPackageBytesV2
    from src.infrastructure.plugins.v2.tool_set import ToolSetContributionCatalogProtocolV2

logger = logging.getLogger(__name__)

_SERVICE = "service:operation.signed-project-packages"


@dataclass
class ProjectPackageCapabilities:
    operation: OperationContextV2
    scope: ScopeBindingV2
    sessions: async_sessionmaker[AsyncSession]
    keys: tuple[str, ...]
    skills: dict[str, tuple[AgentPackagePin, str, Skill]]
    tools: list[ToolDefinition]
    run_id: str
    subagents: dict[str, SignedProjectSubAgent]
    detached_child: bool
    pins: tuple[AgentPackagePin, ...] = ()

    @property
    def loop_pin(self) -> AgentPackagePin | None:
        drivers = [pin for pin in self.pins if pin.drives_agent_loop]
        if len(drivers) > 1:
            raise RuntimeV2Error("agent_loop_conflict", "multiple signed loop drivers")
        return drivers[0] if drivers else None

    def loop_driver(self) -> Callable[[str, str, int], Awaitable[str]]:
        pin = self.loop_pin

        async def advance(phase: str, outcome: str, steps: int) -> str:
            if pin is None:
                raise RuntimeV2Error("agent_loop_missing", "project has no authorized Agent loop")
            self.check_scope(pin.tenant_id, pin.project_id)
            async with self.sessions() as db:

                async def authorize() -> None:
                    self.check_scope(pin.tenant_id, pin.project_id)
                    if not await self.actor_can_execute(db):
                        raise RuntimeV2Error(
                            "package_execution_forbidden", "Agent loop access ended"
                        )

                await authorize()
                service = ProjectPluginInstallationService(
                    db, self.scope, self.keys, actor_id=self.actor_id(), run_id=self.run_id
                )
                result = await service.invoke_pinned_tool(
                    pin,
                    "react_loop",
                    {"phase": phase, "outcome": outcome, "steps": steps},
                    wait_for_slot=True,
                    run_pins=self.pins,
                    check_access=authorize,
                )
                # Revocation while the worker was running fences its instruction.
                await authorize()
                await service.pinned_package(pin)
                action = result.get("action")
                if not isinstance(action, str):
                    raise RuntimeV2Error("agent_loop_invalid", "invalid loop instruction")
                return action

        return advance

    def check_scope(self, tenant: str, project: str) -> None:
        if (
            self.operation is not current_operation_context_v2()
            or self.operation.phase is not FiberPhaseV2.ACTIVE
            or tenant != self.scope.tenant_id
            or project != self.scope.project_id
        ):
            raise RuntimeV2Error("package_scope_changed", "signed package operation scope changed")

    def actor_id(self) -> str:
        identity = self.operation.require(OPERATION_IDENTITY_SERVICE_V2)
        user_id = identity.get("user_id") if isinstance(identity, Mapping) else None
        if not isinstance(user_id, str):
            raise RuntimeV2Error("package_scope_changed", "signed package actor is unavailable")
        return user_id

    async def actor_can_execute(self, db: AsyncSession) -> bool:
        user = await db.get(User, self.actor_id(), populate_existing=True)
        if user is None or not user.is_active:
            raise RuntimeV2Error("package_scope_changed", "signed package actor is unavailable")
        return await project_package_actor_can_execute(
            db,
            current_user=user,
            requested_scope=ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id=self.scope.tenant_id,
                project_id=self.scope.project_id,
            ),
        )

    def tool_definition(
        self, pin: AgentPackagePin, raw_name: str, schema: dict[str, Any], description: str
    ) -> ToolDefinition:
        async def execute(**payload: object) -> str:
            self.check_scope(pin.tenant_id, pin.project_id)
            async with self.sessions() as db:

                async def authorize() -> None:
                    self.check_scope(pin.tenant_id, pin.project_id)
                    if not await self.actor_can_execute(db):
                        raise RuntimeV2Error(
                            "package_execution_forbidden",
                            "project package execution permission is required",
                        )

                await authorize()
                service = ProjectPluginInstallationService(
                    db, self.scope, self.keys, actor_id=self.actor_id(), run_id=self.run_id
                )
                result = await service.invoke_pinned_tool(
                    pin, raw_name, payload, run_pins=self.pins, check_access=authorize
                )
            return json.dumps(result, ensure_ascii=False, allow_nan=False)

        return ToolDefinition(
            name=package_model_name(pin.plugin_id, raw_name, "_"),
            description=f"{pin.plugin_id} / {raw_name}. {description or schema.get('description', '')}".rstrip(),
            parameters=schema.copy(),
            execute=execute,
            permission="code_executor",
        )

    async def load_skill(self, tenant: str, project: str, name: str) -> Skill | None:
        self.check_scope(tenant, project)
        if name not in self.skills:
            return None
        pin, skill_id, skill = self.skills[name]
        async with self.sessions() as db:
            await self.actor_can_execute(db)  # Also verifies read access for viewers.
            service = ProjectPluginInstallationService(db, self.scope, self.keys)
            package = await service.pinned_package(pin)
            for declaration in package.contribution.skills:
                if (
                    declaration.skill_id == skill_id
                    and "skills.register" in package.approved_permissions
                    and declaration.permissions <= package.approved_permissions
                ):
                    return skill
        raise RuntimeV2Error("package_skill_unavailable", "signed Skill authorization ended")

    async def authorize_subagent(
        self, agent: SignedProjectSubAgent, tenant: str, project: str
    ) -> SignedProjectSubAgent:
        self.check_scope(tenant, project)
        selected = self.subagents.get(agent.name)
        if (
            selected is None
            or selected.pin != agent.pin
            or selected.declaration_id != agent.declaration_id
        ):
            raise RuntimeV2Error(
                "package_subagent_unavailable", "signed SubAgent is outside this run"
            )
        async with self.sessions() as db:
            if not await self.actor_can_execute(db):
                raise RuntimeV2Error(
                    "package_execution_forbidden",
                    "project package execution permission is required",
                )
            package = await ProjectPluginInstallationService(
                db, self.scope, self.keys
            ).pinned_package(agent.pin)
            for row in package.contribution.subagents:
                if (
                    row.agent_id == agent.declaration_id
                    and row.permissions <= package.approved_permissions
                ):
                    return signed_subagent(agent.pin, row)
        raise RuntimeV2Error("package_subagent_unavailable", "signed SubAgent authorization ended")

    def register_subagents(
        self, pin: AgentPackagePin, package: SignedPackageBytesV2, can_execute: bool
    ) -> None:
        if can_execute:
            for declaration in package.contribution.subagents:
                if declaration.permissions <= package.approved_permissions:
                    agent = signed_subagent(pin, declaration)
                    self.subagents[agent.name] = agent


async def bind_project_packages(
    operation: OperationContextV2,
    catalog: ToolSetContributionCatalogProtocolV2,
    run_id: str,
    sessions: async_sessionmaker[AsyncSession],
    *,
    trusted_keys: Sequence[str] | None = None,
    detached_child: bool = False,
) -> ProjectPackageCapabilities:
    if operation is not current_operation_context_v2():
        raise RuntimeV2Error("package_scope_changed", "signed package operation scope changed")
    scope = operation.context.scope
    if not scope.tenant_id or not scope.project_id:
        raise RuntimeV2Error("package_scope_changed", "signed package requires a project")
    target = ScopeBindingV2(tenant_id=scope.tenant_id, project_id=scope.project_id)
    if trusted_keys is None:
        from src.infrastructure.plugins.package_registry import load_plugin_trust_keys

        trusted_keys = await asyncio.to_thread(
            load_plugin_trust_keys, get_settings().plugin_marketplace_trusted_key_files
        )
    capabilities = ProjectPackageCapabilities(
        operation=operation,
        scope=target,
        sessions=sessions,
        keys=tuple(trusted_keys),
        skills={},
        tools=[],
        run_id=run_id,
        subagents={},
        detached_child=detached_child,
    )
    async with sessions() as db:
        service = ProjectPluginInstallationService(db, target, capabilities.keys)
        pins = await service.pin_agent_run(run_id)
        capabilities.pins = pins
        can_execute = bool(pins) and await capabilities.actor_can_execute(db)
        for pin in pins:
            # The dedicated model contract is bound by the host's transport, never offered to the model.
            if pin.chat_adapter:
                continue
            try:
                package = await service.pinned_package(pin)
                await service.resolve_service_pins(package, pins)
            except (OptionalBusinessError, ValueError) as error:
                # An unusable release contributes nothing to this operation. Other
                # packages and core tools keep their own independent authorizations.
                logger.warning(
                    "Omitting signed Agent release %s@%s (%s)",
                    pin.plugin_id,
                    pin.version,
                    error.code
                    if isinstance(error, OptionalBusinessError)
                    else type(error).__name__,
                )
                continue
            package_tools: list[str] = []
            for tool in package.contribution.tools:
                if (
                    can_execute
                    and "agent.loop.drive" not in tool.permissions
                    and "tools.execute" in package.approved_permissions
                    and tool.permissions <= package.approved_permissions
                ):
                    tool_definition = capabilities.tool_definition(
                        pin, tool.name, tool.input_schema, tool.description
                    )
                    capabilities.tools.append(tool_definition)
                    package_tools.append(tool_definition.name)
            for row in package.contribution.skills:
                if (
                    "skills.register" not in package.approved_permissions
                    or not row.permissions <= package.approved_permissions
                ):
                    continue
                name = package_model_name(pin.plugin_id, row.skill_id, "-")
                skill = Skill(
                    id=f"{pin.plugin_id}@{pin.digest}/{row.skill_id}",
                    tenant_id=target.tenant_id,
                    project_id=target.project_id,
                    name=name,
                    description=f"{pin.plugin_id} / {row.skill_id}"[:1024],
                    tools=package_tools.copy() or ["skill_loader"],
                    full_content=row.instructions,
                    scope=SkillScope.PROJECT,
                    source=SkillSource.PLUGIN,
                )
                capabilities.skills[name] = (pin, row.skill_id, skill)
            capabilities.register_subagents(pin, package, can_execute)
    if capabilities.tools:
        await contribute_operation_tool_definitions_v2(
            operation=operation,
            catalog=catalog,
            source_id="project-signed-package-tools",
            definitions=capabilities.tools,
        )
    _ = operation.provide(_SERVICE, capabilities)
    return capabilities


def current_package_capabilities() -> ProjectPackageCapabilities | None:
    try:
        operation = current_operation_context_v2()
        catalog = operation.require(_SERVICE)
    except RuntimeV2Error as error:
        if error.code in {"operation_context_not_pinned", "missing_service"}:
            return None
        raise
    if not isinstance(catalog, ProjectPackageCapabilities):
        raise RuntimeV2Error("invalid_package_catalog", "invalid operation package catalog")
    return catalog


async def _distribution_loop(phase: str, outcome: str, steps: int) -> str:
    from plugins.business.agent.react_loop import next_action

    return next_action(phase, outcome, steps)


def current_loop_driver() -> Callable[[str, str, int], Awaitable[str]]:
    catalog = current_package_capabilities()
    return catalog.loop_driver() if catalog is not None else _distribution_loop


async def load_operation_package_skill(tenant: str, project: str, name: str) -> Skill | None:
    catalog = current_package_capabilities()
    return await catalog.load_skill(tenant, project, name) if catalog is not None else None
