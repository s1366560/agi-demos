"""Immutable ToolSet inheritance across SubAgent operation boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import ToolSetV2, restrict_tool_set_v2


class _ToolSetOwnerOperationV2(Protocol):
    @property
    def operation_id(self) -> str: ...

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2: ...

    @property
    def phase(self) -> FiberPhaseV2: ...


@dataclass(frozen=True, kw_only=True)
class InheritedToolSetV2:
    """One immutable parent-visible ToolSet tied to an exact generation."""

    tool_set: ToolSetV2
    generation_descriptor: PluginGenerationDescriptorV2
    owner_operation_id: str
    rebindable_tool_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        snapshot = restrict_tool_set_v2(self.tool_set, self.tool_set.definitions)
        rebindable = frozenset(
            name.strip()
            for name in self.rebindable_tool_names
            if isinstance(name, str) and name.strip()
        )
        unknown = rebindable - set(snapshot.tools)
        if unknown:
            raise RuntimeV2Error(
                "subagent_tool_set_expansion",
                "SubAgent rebindable tools must be visible in the inherited ToolSet",
            )
        if not self.owner_operation_id.strip():
            raise RuntimeV2Error(
                "invalid_subagent_tool_set_owner",
                "SubAgent ToolSet owner operation must be non-empty",
            )
        object.__setattr__(self, "tool_set", snapshot)
        object.__setattr__(self, "rebindable_tool_names", rebindable)

    def validate_generation(self, descriptor: PluginGenerationDescriptorV2) -> None:
        """Reject inheritance across generation version/digest boundaries."""
        if self.generation_descriptor != descriptor:
            raise RuntimeV2Error(
                "subagent_tool_set_generation_mismatch",
                "SubAgent ToolSet generation does not match the child operation",
            )


@dataclass(kw_only=True)
class SubAgentToolSetBindingV2:
    """Bind a late-resolved turn ToolSet exactly once for captured callbacks."""

    operation: _ToolSetOwnerOperationV2
    _inherited: InheritedToolSetV2 | None = field(default=None, init=False, repr=False)

    def bind(
        self,
        tool_set: ToolSetV2,
        *,
        rebindable_tool_names: Iterable[str] = (),
    ) -> InheritedToolSetV2:
        """Copy and bind the finalized parent ToolSet without exposing mutable inputs."""
        self._ensure_owner_active()
        if self._inherited is not None:
            raise RuntimeV2Error(
                "subagent_tool_set_already_bound",
                "SubAgent ToolSet binding can only be completed once",
            )
        inherited = InheritedToolSetV2(
            tool_set=tool_set,
            generation_descriptor=self.operation.descriptor,
            owner_operation_id=self.operation.operation_id,
            rebindable_tool_names=frozenset(rebindable_tool_names),
        )
        self._inherited = inherited
        return inherited

    def require(self) -> InheritedToolSetV2:
        """Return the exact bound snapshot while its owner operation is active."""
        self._ensure_owner_active()
        if self._inherited is None:
            raise RuntimeV2Error(
                "subagent_tool_set_not_bound",
                "SubAgent ToolSet was requested before turn resolution completed",
            )
        self._inherited.validate_generation(self.operation.descriptor)
        return self._inherited

    def _ensure_owner_active(self) -> None:
        if self.operation.phase is not FiberPhaseV2.ACTIVE:
            raise RuntimeV2Error(
                "subagent_tool_set_owner_inactive",
                "SubAgent ToolSet owner operation is no longer active",
            )


__all__ = ["InheritedToolSetV2", "SubAgentToolSetBindingV2"]
