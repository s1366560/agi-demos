"""Catalog unification and structural model-role assessments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.llm_providers.provider_catalog import (
    static_provider_models,
    static_provider_models_document,
)
from src.domain.llm_providers.role_fit import ModelSignals, assess_model_roles
from src.domain.llm_providers.security_policy import (
    environment_credential_endpoint_is_official,
    validate_provider_base_url,
)
from src.infrastructure.llm.provider_guidance import build_provider_guidance

pytestmark = pytest.mark.unit

_ROSTER_PATH = Path("src/infrastructure/llm/static_provider_models.json")


def test_static_roster_json_matches_the_catalog() -> None:
    committed = json.loads(_ROSTER_PATH.read_text(encoding="utf-8"))
    assert committed == static_provider_models_document()


def test_xai_us_endpoint_still_comes_from_the_shared_catalog() -> None:
    assert validate_provider_base_url("https://us.api.x.ai/v1", "xai") == "https://us.api.x.ai/v1"
    assert environment_credential_endpoint_is_official("xai", "https://us.api.x.ai/v1")


def test_static_roster_keeps_current_and_previous_model_ids() -> None:
    openai = static_provider_models("openai")
    assert openai["chat"][:3] == ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"]
    assert "gpt-4o" in openai["chat"]
    assert static_provider_models("kimi_coding") == {}


def test_role_fit_does_not_infer_audio_from_the_model_name() -> None:
    roles = {
        item.role: item
        for item in assess_model_roles(
            ModelSignals(name="gpt-4o-audio-preview", capabilities=frozenset({"chat"}), known=True),
            provider_type="openai",
        )
    }
    assert roles["primary"].supported is True
    assert roles["voice"].supported is False
    assert roles["voice"].reason == "audio_input_not_declared"

    declared = {
        item.role: item
        for item in assess_model_roles(
            ModelSignals(
                name="gpt-4o-audio-preview",
                capabilities=frozenset({"chat"}),
                known=True,
                audio_declared=True,
            ),
            provider_type="openai",
        )
    }
    assert declared["voice"].supported is True


def test_embedding_model_cannot_fill_the_primary_role() -> None:
    roles = {
        item.role: item
        for item in assess_model_roles(
            ModelSignals(
                name="text-embedding-3-small", capabilities=frozenset({"embedding"}), known=True
            ),
            provider_type="openai",
        )
    }
    assert roles["primary"].supported is False
    assert roles["primary"].reason == "not_a_chat_model"
    assert roles["embedding"].supported is True


def test_guidance_explains_providers_without_embedding_or_rerank() -> None:
    guidance = build_provider_guidance("anthropic")
    by_role = {item["role"]: item for item in guidance["roles"]}
    assert by_role["primary"]["default_model"] == "claude-opus-5-5"
    assert by_role["fast"]["default_model"] == "claude-haiku-5-5"
    assert by_role["embedding"]["available"] is False
    assert by_role["embedding"]["reason"] == "provider_has_no_embedding_models"
    assert by_role["rerank"]["reason"] == "provider_has_no_rerank_models"
    assert by_role["voice"]["reason"] == "audio_input_not_declared"


def test_guidance_profiles_include_limits_for_known_snapshot_models() -> None:
    guidance = build_provider_guidance("xai")
    grok = next(profile for profile in guidance["profiles"] if profile["id"] == "grok-4.7")
    assert grok["known"] is True
    assert grok["context_window"] > 0
    assert grok["max_output_tokens"] > 0
    assert "roles" in grok
    assert grok["roles"]["embedding"]["supported"] is False
