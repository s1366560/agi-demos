"""Darwinian Evolver Skill contribution owned by a protocol-v2 Fiber."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from src.domain.model.agent.skill import Skill

from .agent_capabilities import AgentCapabilityCatalogProtocolV2
from .packaged_skill import build_packaged_skill_v2
from .runtime import ContextV2, RuntimeV2Error

DARWINIAN_EVOLVER_SKILL_MODULE_V2 = "builtin://memstack/agent/skill/darwinian-evolver"
DARWINIAN_EVOLVER_DEFAULTS_SERVICE_V2 = "service:darwinian-evolver-defaults"

_DARWINIAN_EVOLVER_SOURCE_V2 = "builtin-darwinian-evolver-skill"
_DARWINIAN_EVOLVER_SKILL_DIGEST_V2 = (
    "sha256:f2a8a119a1fac2b3a8f9c7cf922650b2bc62b7bf68eda13b1e0c748fa4e5a54a"
)
_SKILL_DIRECTORY_V2 = Path(__file__).resolve().parent / "skills" / "darwinian-evolver"
_DARWINIAN_EVOLVER_DEFAULTS_V2: dict[str, object] = {
    "cache_dir": "~/.memstack/cache/darwinian-evolver",
    "default_model": "openai/gpt-4o-mini",
    "default_iterations": 3,
    "default_parent_count": 2,
    "default_concurrency": 2,
    "skill_dir": str(_SKILL_DIRECTORY_V2),
}


def _darwinian_evolver_skills_v2(
    *,
    tenant_id: str,
    project_id: str,
    **_kwargs: object,
) -> list[Skill]:
    return [
        build_packaged_skill_v2(
            skill_name="darwinian-evolver",
            expected_digest=_DARWINIAN_EVOLVER_SKILL_DIGEST_V2,
            tenant_id=tenant_id,
            project_id=None,
        )
    ]


def _apply_darwinian_evolver_skill_contribution_v2(  # pyright: ignore[reportUnusedFunction]
    context: ContextV2,
    config: Mapping[str, Any],
) -> object:
    source_id = config.get("source_id")
    if source_id != _DARWINIAN_EVOLVER_SOURCE_V2:
        raise ValueError(
            "Darwinian Evolver contribution requires source_id "
            "builtin-darwinian-evolver-skill"
        )
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCapabilityCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Darwinian Evolver received an invalid capability catalog",
        )
    contribution_config = {
        key: value for key, value in config.items() if key != "source_id"
    }
    defaults = MappingProxyType(
        {**_DARWINIAN_EVOLVER_DEFAULTS_V2, **contribution_config}
    )
    _ = context.provide(
        DARWINIAN_EVOLVER_DEFAULTS_SERVICE_V2,
        defaults,
        label="darwinian-evolver-defaults",
    )
    return catalog.register_skills(source_id, _darwinian_evolver_skills_v2)


__all__ = [
    "DARWINIAN_EVOLVER_DEFAULTS_SERVICE_V2",
    "DARWINIAN_EVOLVER_SKILL_MODULE_V2",
]
