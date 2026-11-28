"""Project-owned SubAgent declarations for the canonical run's selected releases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

if TYPE_CHECKING:
    from memstack_plugin_sdk.contract import SubAgentContribution

    from plugins.business.agent.engine.processor import ToolDefinition
    from src.domain.model.agent.subagent_run import SubAgentRun
    from src.host.packages.project_plugin_installation import AgentPackagePin


def package_model_name(plugin: str, name: str, separator: str, *scope: object) -> str:
    stem = re.sub(r"[^a-z0-9]+", separator, f"package-{plugin}-{name}".lower()).strip(separator)
    suffix = hashlib.sha256(json.dumps([plugin, name, *scope]).encode()).hexdigest()[:12]
    return f"{stem[:51].rstrip(separator)}{separator}{suffix}"


@dataclass(kw_only=True)
class SignedProjectSubAgent(SubAgent):
    pin: AgentPackagePin
    declaration_id: str

    def release_binding(self) -> dict[str, object]:
        return {**asdict(self.pin), "declaration_id": self.declaration_id}


def signed_subagent(pin: AgentPackagePin, row: SubAgentContribution) -> SignedProjectSubAgent:
    # Policies can reference the stable id. The session registry uses the versioned
    # name so a follow-up from a newer turn cannot restart a retired declaration.
    return SignedProjectSubAgent(
        pin=pin,
        declaration_id=row.agent_id,
        id=package_model_name(pin.plugin_id, row.agent_id, "-"),
        name=package_model_name(
            pin.plugin_id, row.agent_id, "-", pin.digest, pin.authorization_epoch
        ),
        tenant_id=pin.tenant_id,
        project_id=pin.project_id,
        display_name=row.name,
        system_prompt=row.instructions,
        trigger=AgentTrigger(description=row.description),
        allowed_tools=[package_model_name(pin.plugin_id, name, "_") for name in row.tools],
        spawn_policy=SpawnPolicy(max_depth=0, allowed_subagents=frozenset()),
    )


def subagent_policy_identifiers(subagent: SubAgent) -> tuple[str, ...]:
    if isinstance(subagent, SignedProjectSubAgent):
        return (subagent.id, subagent.name)
    return tuple(
        value.strip()
        for key in ("id", "name", "display_name")
        if isinstance(value := getattr(subagent, key, None), str) and value.strip()
    )


async def authorize_signed_subagent(subagent: SubAgent, tenant: str, project: str) -> SubAgent:
    if not isinstance(subagent, SignedProjectSubAgent):
        return subagent
    from src.infrastructure.agent.core.project_package_tools import current_package_capabilities

    catalog = current_package_capabilities()
    if catalog is None:
        raise RuntimeV2Error("package_subagent_unavailable", "missing signed SubAgent authority")
    return await catalog.authorize_subagent(subagent, tenant, project)


def signed_subagent_tools(
    subagent: SignedProjectSubAgent, inherited: list[ToolDefinition]
) -> list[ToolDefinition]:
    """Bind only selected, parent-visible tools to this operation, including detached forks."""
    from src.infrastructure.agent.core.project_package_tools import current_package_capabilities

    catalog = current_package_capabilities()
    if catalog is None:
        raise RuntimeV2Error("package_subagent_unavailable", "missing signed SubAgent authority")
    owned = {tool.name: tool for tool in catalog.tools if tool.name in subagent.allowed_tools}
    if not catalog.detached_child:
        return [tool for tool in inherited if tool.name in owned]
    return [
        replace(tool, execute=owned[tool.name].execute) for tool in inherited if tool.name in owned
    ]


async def require_signed_continuation(run: SubAgentRun) -> None:
    """Send/steer must not reassign an existing session to a different release or grant."""
    expected = run.metadata.get("signed_subagent_release")
    if expected is None:
        return
    from src.infrastructure.agent.core.project_package_tools import current_package_capabilities

    catalog = current_package_capabilities()
    agent = catalog.subagents.get(run.subagent_name) if catalog else None
    if agent is None or agent.release_binding() != expected:
        raise RuntimeV2Error(
            "package_subagent_unavailable", "signed SubAgent release is outside this run"
        )
    await authorize_signed_subagent(agent, agent.pin.tenant_id, agent.pin.project_id)
