"""Pure runtime value objects shared by platform plugin ports."""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import PluginScope


@dataclass(frozen=True)
class PluginScopeContext:
    """Immutable identity passed to a plugin capability call."""

    tenant_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None

    @property
    def default_scope(self) -> PluginScope:
        """Return the narrowest scope represented by this context."""
        if self.session_id is not None:
            return PluginScope.SESSION
        if self.project_id is not None:
            return PluginScope.PROJECT
        if self.tenant_id is not None:
            return PluginScope.TENANT
        return PluginScope.GLOBAL

    def cache_key(self) -> tuple[str | None, str | None, str | None]:
        """Return the stable identity tuple used by capability caches."""
        return self.tenant_id, self.project_id, self.session_id


@dataclass(frozen=True)
class CredentialReference:
    """Opaque reference to a host-owned credential.

    The value is deliberately absent. Only an execution boundary with an explicit
    grant may resolve it, which prevents provider plugins from persisting keys.
    """

    ref: str
    revision: int


@dataclass(frozen=True)
class PluginGeneration:
    """One immutable activation generation of plugin capabilities."""

    profile_digest: str
    sequence: int
