"""Unit tests for models.dev catalog conversion helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.llm_providers.models import ModelCapability, ModelMetadata
from src.infrastructure.llm.models_dev_fetcher import (
    _convert_single_model,
    _derive_capabilities,
    _metadata_to_dict,
    _parse_models_dev_payload,
    convert_to_model_metadata,
    fetch_models_dev,
    generate_snapshot,
)

pytestmark = pytest.mark.unit


def _chat_model_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "GPT Test",
        "id": "gpt-test",
        "modalities": {"input": ["text"], "output": ["text"]},
        "limit": {"context": 128000, "output": 4096, "input": 120000},
        "cost": {"input": 1.0, "output": 2.0, "cache_read": 0.1},
        "release_date": "2025-01-02",
        "family": "gpt",
        "tool_call": True,
        "structured_output": True,
        "attachment": True,
        "knowledge": "2024-12",
    }
    payload.update(overrides)
    return payload


def test_parse_models_dev_payload_requires_object() -> None:
    assert _parse_models_dev_payload('{"openai": {"models": {}}}') == {"openai": {"models": {}}}

    with pytest.raises(ValueError, match="JSON object"):
        _parse_models_dev_payload("[]")


def test_fetch_models_dev_can_read_local_payload(tmp_path: Path) -> None:
    payload_path = tmp_path / "models.json"
    payload_path.write_text('{"openai": {"models": {}}}', encoding="utf-8")

    assert fetch_models_dev(local_path=payload_path) == {"openai": {"models": {}}}


def test_convert_to_model_metadata_includes_embedding_and_missing_providers() -> None:
    raw = {
        "openai": {
            "models": {
                "gpt-test": _chat_model_payload(),
                "embed-test": _chat_model_payload(
                    name="Embedding Test",
                    id="embed-test",
                    family="embedding",
                    modalities={"input": ["text"], "output": []},
                    tool_call=False,
                    structured_output=False,
                ),
            }
        }
    }

    converted = convert_to_model_metadata(
        raw,
        providers={"openai": "openai", "missing": "missing"},
    )

    assert list(converted) == ["gpt-test", "embed-test"]
    meta = converted["gpt-test"]
    assert meta.provider == "openai"
    assert meta.context_length == 128000
    assert meta.max_input_tokens == 120000
    assert meta.supports_tool_call is True
    assert meta.supports_response_format is True
    assert meta.supports_seed is True
    assert meta.temperature_range == [0.0, 2.0]
    assert ModelCapability.FUNCTION_CALLING.value in meta.capabilities

    embedding_meta = converted["embed-test"]
    assert embedding_meta.provider == "openai"
    assert embedding_meta.supports_streaming is False
    assert embedding_meta.supports_json_mode is False
    assert embedding_meta.supports_temperature is False
    assert embedding_meta.supports_top_p is False
    assert embedding_meta.capabilities == [ModelCapability.EMBEDDING.value]


def test_convert_single_model_applies_reasoning_and_budget_overrides() -> None:
    meta = _convert_single_model(
        "qwen-max",
        _chat_model_payload(
            id="qwen-max",
            limit={"context": 32768, "output": 2048},
            reasoning=True,
            temperature=False,
            family="qwen-coder",
            modalities={"input": ["text", "image"], "output": ["text"]},
        ),
        "dashscope",
    )

    assert meta is not None
    assert meta.max_input_tokens is None
    assert meta.input_budget_ratio == 0.85
    assert meta.chars_per_token == 1.2
    assert meta.reasoning is True
    assert meta.supports_temperature is False
    assert meta.supports_stop is False
    assert meta.supports_top_p is False
    assert ModelCapability.VISION.value in meta.capabilities
    assert ModelCapability.CODE.value in meta.capabilities


def test_convert_single_model_handles_invalid_release_date() -> None:
    meta = _convert_single_model(
        "claude-test",
        _chat_model_payload(release_date="not-a-date", temperature=True),
        "anthropic",
    )

    assert meta is not None
    assert meta.release_date is None
    assert meta.temperature_range == [0.0, 1.0]
    assert meta.supports_frequency_penalty is False
    assert meta.supports_presence_penalty is False


def test_derive_capabilities_combines_tools_vision_and_code() -> None:
    caps = _derive_capabilities(
        "devstral-test",
        {
            "id": "devstral-test",
            "family": "code",
            "tool_call": True,
            "modalities": {"input": ["text", "video"]},
        },
    )

    assert caps == [
        ModelCapability.CHAT,
        ModelCapability.FUNCTION_CALLING,
        ModelCapability.VISION,
        ModelCapability.CODE,
    ]


def test_convert_single_model_classifies_rerank_models() -> None:
    meta = _convert_single_model(
        "qwen3-rerank",
        _chat_model_payload(
            name="Qwen3 Rerank",
            id="qwen3-rerank",
            family="rerank",
            modalities={"input": ["text"], "output": []},
            tool_call=False,
            structured_output=False,
        ),
        "dashscope",
    )

    assert meta is not None
    assert meta.capabilities == [ModelCapability.RERANK.value]
    assert meta.supports_streaming is False
    assert meta.supports_response_format is False


def test_metadata_to_dict_and_generate_snapshot_are_deterministic(tmp_path: Path) -> None:
    meta = ModelMetadata(
        name="model-a",
        provider="openai",
        context_length=10000,
        max_output_tokens=1000,
        input_cost_per_1m=1.0,
        output_cost_per_1m=2.0,
        capabilities=[ModelCapability.CHAT],
        supports_json_mode=True,
        modalities=["text"],
        family="gpt",
        input_budget_ratio=0.8,
        chars_per_token=2.5,
        supports_tool_call=True,
        supports_response_format=True,
        temperature_range=[0.0, 2.0],
        top_p_range=[0.0, 1.0],
    )

    serialized = _metadata_to_dict(meta)
    assert serialized["capabilities"] == ["chat"]
    assert serialized["input_budget_ratio"] == 0.8
    assert serialized["supports_tool_call"] is True

    output_path = generate_snapshot({"model-a": meta}, output_path=tmp_path / "snapshot.json")
    snapshot = json.loads(output_path.read_text(encoding="utf-8"))

    assert snapshot["_meta"]["model_count"] == 1
    assert snapshot["models"]["model-a"]["provider"] == "openai"
