"""Pure runtime value objects shared by platform plugin ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True, kw_only=True)
class PluginGenerationDescriptorV2:
    """Serializable identity for one v2 generation, without host runtime objects."""

    profile_id: str
    generation: int
    digest: str

    def to_payload(self) -> dict[str, str | int]:
        return {
            "profile_id": self.profile_id,
            "generation": self.generation,
            "digest": self.digest,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PluginGenerationDescriptorV2:
        if set(payload) != {"profile_id", "generation", "digest"}:
            raise ValueError("plugin generation descriptor has invalid fields")
        profile_id = payload["profile_id"]
        generation = payload["generation"]
        digest = payload["digest"]
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("plugin generation profile_id must be non-empty")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("plugin generation must be a positive integer")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("plugin generation digest must be lowercase sha256 hex")
        return cls(profile_id=profile_id, generation=generation, digest=digest)
