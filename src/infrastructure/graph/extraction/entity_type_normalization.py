"""Canonical entity type normalization for extraction outputs."""

from collections.abc import Collection

DEFAULT_ENTITY_TYPE = "Entity"

_LOCALIZED_BUILTIN_ALIASES = {
    "人物": "Person",
    "人员": "Person",
    "人": "Person",
    "个人": "Person",
    "组织": "Organization",
    "机构": "Organization",
    "公司": "Organization",
    "企业": "Organization",
    "地点": "Location",
    "位置": "Location",
    "地方": "Location",
    "城市": "Location",
    "概念": "Concept",
    "事件": "Event",
    "物品": "Artifact",
    "人工制品": "Artifact",
    "作品": "Artifact",
}


def normalize_entity_type(
    value: object,
    *,
    allowed_types: Collection[str] | None = None,
) -> str:
    """Normalize multilingual LLM type labels to canonical graph schema names."""
    if not isinstance(value, str):
        return DEFAULT_ENTITY_TYPE

    candidate = value.strip()
    if not candidate:
        return DEFAULT_ENTITY_TYPE

    if allowed_types:
        allowed_by_lower = {allowed_type.lower(): allowed_type for allowed_type in allowed_types}
        exact_match = allowed_by_lower.get(candidate.lower())
        if exact_match:
            return exact_match

    alias = _LOCALIZED_BUILTIN_ALIASES.get(candidate)
    if alias and (not allowed_types or alias in allowed_types):
        return alias

    return candidate
