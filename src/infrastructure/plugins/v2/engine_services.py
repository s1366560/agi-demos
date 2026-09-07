"""Generation-owned engine catalog Provider for protocol v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ENGINE_CATALOG_MODULE_V2 = "builtin://memstack/application/engine-catalog"
ENGINE_CATALOG_SERVICE_V2 = "service:application.engine-catalog"


@dataclass(frozen=True, kw_only=True)
class EngineDescriptorV2:
    """Immutable public metadata for one generation-declared runtime engine."""

    runtime_id: str
    display_name: str
    display_description: str
    display_tags: tuple[str, ...]
    display_powered_by: str
    order: int
    image_registry_key: str
    default_registry_url: str

    def to_public_dict(self) -> dict[str, Any]:
        """Return the stable HTTP representation of this engine descriptor."""
        return {
            "runtime_id": self.runtime_id,
            "display_name": self.display_name,
            "display_description": self.display_description,
            "display_tags": list(self.display_tags),
            "display_powered_by": self.display_powered_by,
            "order": self.order,
            "image_registry_key": self.image_registry_key,
            "default_registry_url": self.default_registry_url,
        }


@runtime_checkable
class EngineCatalogProtocolV2(Protocol):
    """Consumer-facing engine catalog seam for one pinned generation."""

    def list_engines(self) -> tuple[EngineDescriptorV2, ...]: ...


@dataclass(frozen=True, kw_only=True)
class EngineCatalogV2:
    """Ordered engine descriptors built only from one explicit Profile entry."""

    engines: tuple[EngineDescriptorV2, ...]

    def __post_init__(self) -> None:
        runtime_ids: set[str] = set()
        for engine in self.engines:
            if not engine.runtime_id.strip():
                raise RuntimeV2Error(
                    "invalid_engine_runtime_id",
                    "engine runtime_id must be non-empty",
                )
            if engine.runtime_id in runtime_ids:
                raise RuntimeV2Error(
                    "duplicate_engine_runtime_id",
                    f"engine runtime_id {engine.runtime_id} is declared more than once",
                )
            runtime_ids.add(engine.runtime_id)
        object.__setattr__(
            self, "engines", tuple(sorted(self.engines, key=lambda item: item.order))
        )

    def list_engines(self) -> tuple[EngineDescriptorV2, ...]:
        return self.engines


def _engine_descriptor_v2(raw: object) -> EngineDescriptorV2:
    if not isinstance(raw, Mapping):
        raise RuntimeV2Error(
            "invalid_engine_catalog_config",
            "engine catalog entries must be objects",
        )
    value = cast("Mapping[str, Any]", raw)
    try:
        return EngineDescriptorV2(
            runtime_id=value["runtime_id"],
            display_name=value["display_name"],
            display_description=value["display_description"],
            display_tags=tuple(value["display_tags"]),
            display_powered_by=value["display_powered_by"],
            order=value["order"],
            image_registry_key=value["image_registry_key"],
            default_registry_url=value["default_registry_url"],
        )
    except (KeyError, TypeError) as exc:
        raise RuntimeV2Error(
            "invalid_engine_catalog_config",
            "engine catalog entry does not match its declared contract",
        ) from exc


def _apply_engine_catalog_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "declared-engines":
        raise ValueError("engine catalog requires strategy declared-engines")
    raw_engines = config.get("engines")
    if not isinstance(raw_engines, list):
        raise RuntimeV2Error(
            "invalid_engine_catalog_config",
            "engine catalog requires an engines array",
        )
    declared_engines = cast("list[object]", raw_engines)
    catalog = EngineCatalogV2(
        engines=tuple(_engine_descriptor_v2(raw) for raw in declared_engines),
    )
    _ = context.provide(
        ENGINE_CATALOG_SERVICE_V2,
        catalog,
        label="engine-catalog",
    )


def engine_catalog_definition_v2() -> PluginDefinitionV2:
    """Return the trusted builtin definition for the engine catalog Provider."""
    return PluginDefinitionV2(
        module_ref=ENGINE_CATALOG_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ENGINE_CATALOG_MODULE_V2),
        apply=_apply_engine_catalog_v2,
    )


__all__ = [
    "ENGINE_CATALOG_MODULE_V2",
    "ENGINE_CATALOG_SERVICE_V2",
    "EngineCatalogProtocolV2",
    "EngineCatalogV2",
    "EngineDescriptorV2",
    "engine_catalog_definition_v2",
]
