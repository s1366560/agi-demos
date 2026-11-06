"""Structural role fit for a model. Names are never treated as capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.llm_providers.audio_input import OPENAI_AUDIO_INPUT_ADAPTERS
from src.domain.llm_providers.provider_catalog import ROLE_ORDER, provider_family

_CHAT_CAPABILITIES = frozenset({"chat", "completion"})
_EMBEDDING_CAPABILITIES = frozenset({"embedding"})
_RERANK_CAPABILITIES = frozenset({"rerank", "reranking"})
_AUDIO_CAPABILITIES = frozenset(
    {
        "tts",
        "asr",
        "audio_generation",
        "voice_cloning",
        "realtime_voice",
    }
)
_AUDIO_MODALITIES = frozenset({"audio"})


@dataclass(frozen=True, slots=True)
class ModelSignals:
    """Capability facts already recorded for a model."""

    name: str
    capabilities: frozenset[str] = frozenset()
    modalities: frozenset[str] = frozenset()
    known: bool = False
    deprecated: bool = False
    audio_declared: bool = False


@dataclass(frozen=True, slots=True)
class RoleAssessment:
    """Whether one routing role can use this model, and why."""

    role: str
    supported: bool
    reason: str


def _normalized(values: frozenset[str]) -> frozenset[str]:
    return frozenset(value.strip().lower() for value in values if value.strip())


def _has_audio_capability(signals: ModelSignals) -> bool:
    return bool(
        signals.capabilities & _AUDIO_CAPABILITIES or signals.modalities & _AUDIO_MODALITIES
    )


def _chat_reason(signals: ModelSignals) -> tuple[bool, str]:
    if not signals.known:
        return True, "unknown_assumed_chat"
    if signals.capabilities & _CHAT_CAPABILITIES:
        return True, "deprecated" if signals.deprecated else "ok"
    if signals.capabilities & (_EMBEDDING_CAPABILITIES | _RERANK_CAPABILITIES):
        return False, "not_a_chat_model"
    return False, "not_a_chat_model"


def assess_model_roles(
    signals: ModelSignals,
    *,
    provider_type: str | None = None,
) -> tuple[RoleAssessment, ...]:
    """Return one assessment for every routing role.

    Unknown model IDs may still be used as chat models. Embedding, rerank, and
    audio stay unsupported until the catalog or an explicit declaration says so.
    """
    capabilities = _normalized(signals.capabilities)
    modalities = _normalized(signals.modalities)
    normalized = ModelSignals(
        name=signals.name,
        capabilities=capabilities,
        modalities=modalities,
        known=signals.known,
        deprecated=signals.deprecated,
        audio_declared=signals.audio_declared,
    )
    chat_supported, chat_reason = _chat_reason(normalized)
    embedding_supported = bool(capabilities & _EMBEDDING_CAPABILITIES or "embedding" in modalities)
    rerank_supported = bool(capabilities & _RERANK_CAPABILITIES)
    audio_allowed = provider_family(provider_type or "") in OPENAI_AUDIO_INPUT_ADAPTERS
    if _has_audio_capability(normalized):
        voice_supported, voice_reason = True, "deprecated" if normalized.deprecated else "ok"
    elif normalized.audio_declared and audio_allowed:
        voice_supported, voice_reason = True, "ok"
    elif not audio_allowed:
        voice_supported, voice_reason = False, "audio_declaration_unsupported"
    else:
        voice_supported, voice_reason = False, "audio_input_not_declared"

    def _reason(supported: bool, reason: str) -> str:
        if supported and normalized.deprecated and reason == "ok":
            return "deprecated"
        return reason

    assessments = {
        "primary": RoleAssessment("primary", chat_supported, chat_reason),
        "fast": RoleAssessment("fast", chat_supported, chat_reason),
        "embedding": RoleAssessment(
            "embedding",
            embedding_supported,
            _reason(
                embedding_supported,
                "ok" if embedding_supported else "embedding_capability_required",
            ),
        ),
        "rerank": RoleAssessment(
            "rerank",
            rerank_supported,
            _reason(rerank_supported, "ok" if rerank_supported else "rerank_capability_required"),
        ),
        "voice": RoleAssessment("voice", voice_supported, voice_reason),
    }
    return tuple(assessments[role] for role in ROLE_ORDER)


def role_for_operation(operation_type: str) -> str:
    """Map a stored operation type onto the role a selected model must fill."""
    if operation_type == "embedding":
        return "embedding"
    if operation_type == "rerank":
        return "rerank"
    return "primary"
