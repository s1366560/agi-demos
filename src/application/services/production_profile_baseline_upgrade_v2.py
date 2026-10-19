"""Explicit upgrade of the reserved production layer, retaining scoped overlays."""

import json
from dataclasses import replace

from src.domain.model.plugins.generated_v2 import ProfileEntryV2, ProfileSourceV2
from src.infrastructure.plugins.v2.layer_composer import profile_source_digest_v2

_LAYER_ID = "memstack-production-target-hosts"
_PROVENANCE = "repo://config/plugin-profiles/memstack-production-target-hosts.v2.yaml"


class ProductionProfileBaselineUpgradeV2Error(ValueError):
    """An explicit maintenance upgrade cannot preserve the existing configuration."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def upgrade_production_profile_baseline_v2(
    source: ProfileSourceV2, production: ProfileSourceV2
) -> ProfileSourceV2:
    """Replace only the reserved layer's entries after checking structural references.

    Provenance identifies a supported migration format, never caller authorization.
    Root initialization and scoped copies retain this lineage in original_provenance.
    Callers must authorize maintenance and persist both source and desired CAS together.
    """
    if not _has_production_lineage(source.provenance):
        raise ProductionProfileBaselineUpgradeV2Error(
            "profile_baseline_lineage_unknown", "source has no production baseline lineage"
        )
    current = [layer for layer in source.layers if layer.layer_id == _LAYER_ID]
    replacement = [layer for layer in production.layers if layer.layer_id == _LAYER_ID]
    if len(current) != 1 or len(replacement) != 1:
        raise ProductionProfileBaselineUpgradeV2Error(
            "profile_baseline_layer_invalid", "exactly one production baseline layer is required"
        )
    previous, target = current[0], replacement[0]
    if (previous.kind, previous.scope) != (target.kind, target.scope):
        raise ProductionProfileBaselineUpgradeV2Error(
            "profile_baseline_layer_invalid", "production baseline layer scope or kind differs"
        )
    retired = {entry.entry_id for entry in previous.entries} - {
        entry.entry_id for entry in target.entries
    }
    references: set[str] = set()
    for layer in source.layers:
        references.update(layer.disabled_entry_ids)
        for entry in layer.replacements:
            references.add(entry.entry_id)
            references.update(_entry_references(entry))
        if layer is not previous:
            for entry in layer.entries:
                references.add(entry.entry_id)
                references.update(_entry_references(entry))
    incompatible = sorted(retired & references)
    if incompatible:
        raise ProductionProfileBaselineUpgradeV2Error(
            "profile_baseline_retired_entry_referenced",
            "explicit overlay migration is required for retired entries: "
            + ", ".join(incompatible),
        )
    updated = replace(previous, entries=target.entries)
    if updated == previous:
        return source
    candidate = replace(
        source,
        revision=source.revision + 1,
        layers=tuple(updated if layer is previous else layer for layer in source.layers),
    )
    return replace(candidate, digest=profile_source_digest_v2(candidate))


def _entry_references(entry: ProfileEntryV2) -> set[str]:
    return {
        *(() if entry.parent_entry_id is None else (entry.parent_entry_id,)),
        *entry.inject.values(),
        *entry.isolate.values(),
    }


def _has_production_lineage(provenance: str | None) -> bool:
    value = provenance
    while isinstance(value, str):
        if value == _PROVENANCE:
            return True
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return False
        value = decoded.get("original_provenance") if isinstance(decoded, dict) else None
    return False
