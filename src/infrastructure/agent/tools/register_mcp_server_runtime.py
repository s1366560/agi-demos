"""Generation-bound runtime binding for the register_mcp_server tool."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo


@dataclass(frozen=True, kw_only=True, slots=True)
class RegisterMCPServerRuntime:
    """Dependencies and scope captured by one generation's registration tool."""

    session_factory: Any | None
    tenant_id: str
    project_id: str
    sandbox_adapter: SandboxPort | None
    sandbox_id: str | None


register_mcp_server_runtime: ContextVar[RegisterMCPServerRuntime | None] = ContextVar(
    f"{__name__}.register_mcp_server_runtime",
    default=None,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundRegisterMCPServerExecutor:
    template: ToolInfo
    runtime: RegisterMCPServerRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = register_mcp_server_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            register_mcp_server_runtime.reset(token)


def make_register_mcp_server_tool(
    *,
    template: ToolInfo,
    session_factory: Any | None = None,
    tenant_id: str = "",
    project_id: str = "",
    sandbox_adapter: SandboxPort | None = None,
    sandbox_id: str | None = None,
) -> ToolInfo:
    """Return a registration ToolInfo bound to one generation dependency set."""
    runtime = RegisterMCPServerRuntime(
        session_factory=session_factory,
        tenant_id=tenant_id,
        project_id=project_id,
        sandbox_adapter=sandbox_adapter,
        sandbox_id=sandbox_id,
    )
    return replace(
        template,
        execute=_BoundRegisterMCPServerExecutor(
            template=template,
            runtime=runtime,
        ),
    )
