from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException


@dataclass
class FeatureDefinition:
    id: str
    name: str
    description: str
    edition: str = "ce"  # "ce" = available in all editions, "ee" = enterprise only
    enabled: bool = True

FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    FeatureDefinition(id="gene_market", name="Gene Market", description="Gene marketplace", edition="ce"),
    FeatureDefinition(id="knowledge_graph", name="Knowledge Graph", description="Neo4j knowledge graph", edition="ce"),
    FeatureDefinition(id="agent_pool", name="Agent Pool", description="Agent pool management", edition="ce"),
    FeatureDefinition(id="mcp_tools", name="MCP Tools", description="Model Context Protocol tools", edition="ce"),
    FeatureDefinition(id="webhooks", name="Webhooks", description="Outbound webhook management", edition="ce"),
    FeatureDefinition(id="events", name="Events", description="System event logging", edition="ce"),
    FeatureDefinition(id="advanced_analytics", name="Advanced Analytics", description="Advanced analytics dashboard", edition="ee"),
    FeatureDefinition(id="sso", name="SSO", description="Single Sign-On", edition="ee"),
]

class FeatureGate:
    def __init__(self) -> None:
        self._edition = os.getenv("MEMSTACK_EDITION", "ce").lower()
        self._overrides: dict[str, bool] = {}

    @property
    def edition(self) -> str:
        return self._edition

    def is_enabled(self, feature_id: str) -> bool:
        if feature_id in self._overrides:
            return self._overrides[feature_id]
        for feat in FEATURE_DEFINITIONS:
            if feat.id == feature_id:
                if feat.edition == "ee" and self._edition != "ee":
                    return False
                return feat.enabled
        return False

    def get_enabled_features(self) -> list[dict[str, Any]]:
        return [
            {"id": f.id, "name": f.name, "description": f.description, "edition": f.edition, "enabled": self.is_enabled(f.id)}
            for f in FEATURE_DEFINITIONS
        ]

# Singleton
_feature_gate: FeatureGate | None = None

def get_feature_gate() -> FeatureGate:
    global _feature_gate
    if _feature_gate is None:
        _feature_gate = FeatureGate()
    return _feature_gate

def require_feature(feature_id: str) -> Any:  # noqa: ANN401
    def dependency() -> None:
        gate = get_feature_gate()
        if not gate.is_enabled(feature_id):
            raise HTTPException(status_code=403, detail=f"Feature '{feature_id}' is not available in {gate.edition} edition")
    return Depends(dependency)
