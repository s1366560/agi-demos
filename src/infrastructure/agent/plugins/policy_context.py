"""Policy context normalization for tool-selection governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

DEFAULT_POLICY_LAYER_ORDER: tuple[str, ...] = (
    "profile",
    "provider",
    "global",
    "tenant",
    "agent",
    "plugin_group",
    "sandbox",
    "subagent",
)


@dataclass(frozen=True)
class PolicyLayer:
    """One policy layer with normalized values."""

    name: str
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyContext:
    """Normalized layered policy context."""

    layers: tuple[PolicyLayer, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Return ordered layer names."""
        return tuple(layer.name for layer in self.layers)

    def to_mapping(self) -> Dict[str, Dict[str, Any]]:
        """Serialize normalized layers to mutable dict mapping."""
        return {layer.name: dict(layer.values) for layer in self.layers}

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, Any],
        *,
        layer_order: Sequence[str] = DEFAULT_POLICY_LAYER_ORDER,
    ) -> PolicyContext:
        """Build normalized policy context from legacy + layered metadata."""
        ordered_names = tuple(layer_order)
        policy_layers = metadata.get("policy_layers")

        raw_layers: Dict[str, Mapping[str, Any]] = {}
        if isinstance(policy_layers, Mapping):
            for key, value in policy_layers.items():
                if isinstance(key, str) and key and isinstance(value, Mapping):
                    raw_layers[key] = value

        for layer_name in ordered_names:
            legacy_value = metadata.get(f"policy_{layer_name}")
            if isinstance(legacy_value, Mapping):
                raw_layers[layer_name] = legacy_value

        remaining_names = sorted(name for name in raw_layers if name not in ordered_names)
        normalized_names = ordered_names + tuple(remaining_names)
        normalized_layers: list[PolicyLayer] = []
        for layer_name in normalized_names:
            values = raw_layers.get(layer_name)
            if not isinstance(values, Mapping):
                continue
            normalized_layers.append(PolicyLayer(name=layer_name, values=dict(values)))

        return cls(layers=tuple(normalized_layers))


def normalize_policy_layers(
    metadata: Mapping[str, Any],
    *,
    layer_order: Sequence[str] = DEFAULT_POLICY_LAYER_ORDER,
) -> Dict[str, Dict[str, Any]]:
    """Return normalized policy layers mapping from metadata."""
    return PolicyContext.from_metadata(metadata, layer_order=layer_order).to_mapping()
