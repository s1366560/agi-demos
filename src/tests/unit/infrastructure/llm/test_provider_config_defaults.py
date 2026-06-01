"""Coverage for provider configuration defaults and environment resolution."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm.provider_config import (
    DEFAULT_MODELS,
    ProviderHealthConfig,
    ProviderPrefix,
    UnifiedLLMConfig,
    get_provider_prefix,
    infer_provider_from_model,
)
from src.infrastructure.llm.provider_env_defaults import (
    PROVIDER_AUTO_DETECT,
    detect_provider_name_from_env,
    provider_type_from_name,
    resolve_provider_env_defaults,
)

pytestmark = pytest.mark.unit


def test_llm_type_contract_module_imports_all_typed_dicts() -> None:
    module = importlib.import_module("src.infrastructure.llm.llm_types")

    message: module.MessageDict = {"role": "user", "content": "hello"}
    tool_call: module.ToolCallDict = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "search", "arguments": "{}"},
    }
    response: module.CompletionResponseDict = {
        "id": "cmpl-1",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    cached: module.CachedResponseDict = {"response": response, "cache_key": "key"}

    assert tool_call["function"]["name"] == "search"
    assert cached["response"]["choices"][0]["message"]["content"] == "hello"
    assert "ProviderConfigDict" in vars(module)


@pytest.mark.parametrize(
    ("provider_type", "expected"),
    [
        (ProviderType.OPENAI, ProviderPrefix.OPENAI),
        (ProviderType.OPENROUTER, ProviderPrefix.OPENAI),
        (ProviderType.DEEPSEEK, ProviderPrefix.DEEPSEEK),
        (ProviderType.KIMI, ProviderPrefix.KIMI),
        (ProviderType.LMSTUDIO, ProviderPrefix.LMSTUDIO),
        (ProviderType.VOLCENGINE, ProviderPrefix.VOLCENGINE),
    ],
)
def test_get_provider_prefix_maps_supported_provider_types(
    provider_type: ProviderType,
    expected: ProviderPrefix,
) -> None:
    assert get_provider_prefix(provider_type) == expected


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("qwen-max", ProviderType.DASHSCOPE),
        ("GPT-4o", ProviderType.OPENAI),
        ("gemini-2.0-flash", ProviderType.GEMINI),
        ("deepseek-chat", ProviderType.DEEPSEEK),
        ("doubao-seed-2.0-pro", ProviderType.VOLCENGINE),
        ("unknown-model", ProviderType.OPENAI),
    ],
)
def test_infer_provider_from_model_uses_known_prefixes(
    model_name: str,
    expected: ProviderType,
) -> None:
    assert infer_provider_from_model(model_name) == expected


def test_unified_llm_config_defaults_and_litellm_names() -> None:
    config = UnifiedLLMConfig(
        provider_type=ProviderType.DASHSCOPE,
        temperature=0.2,
        max_tokens=2048,
        provider_options={"top_p": 0.9},
    )

    assert config.model == "qwen-max"
    assert config.small_model == "qwen-turbo"
    assert config.get_litellm_model_name() == "dashscope/qwen-max"
    assert config.get_litellm_model_name("already/prefixed") == "already/prefixed"
    assert config.get_model_for_size("small") == "qwen-turbo"
    assert config.get_model_for_size("large") == "qwen-max"
    assert config.to_kwargs() == {
        "model": "dashscope/qwen-max",
        "temperature": 0.2,
        "max_tokens": 2048,
        "timeout": 600,
        "top_p": 0.9,
    }


def test_unified_llm_config_keeps_openai_model_unprefixed() -> None:
    config = UnifiedLLMConfig(provider_type=ProviderType.OPENAI, model="gpt-4o")

    assert config.get_litellm_model_name() == "gpt-4o"
    assert config.get_default_model("embedding") == "text-embedding-3-small"
    assert config.get_default_model("missing-operation") == "gpt-4o-mini"


def test_provider_health_config_uses_completion_default() -> None:
    config = ProviderHealthConfig(provider_type=ProviderType.GEMINI)

    assert config.health_check_model == "gemini-2.0-flash"
    assert config.failure_threshold == 5
    assert config.recovery_timeout == 60.0


def test_models_dev_llm_defaults_exist_in_snapshot() -> None:
    snapshot = json.loads(
        Path("src/infrastructure/llm/models_snapshot.json").read_text(encoding="utf-8")
    )
    by_provider: dict[str, set[str]] = {}
    for model in snapshot["models"].values():
        by_provider.setdefault(model["provider"], set()).add(model["name"])

    provider_types = (
        ProviderType.GEMINI,
        ProviderType.KIMI,
        ProviderType.DEEPSEEK,
        ProviderType.MINIMAX,
        ProviderType.ZAI,
        ProviderType.GROQ,
        ProviderType.COHERE,
        ProviderType.BEDROCK,
        ProviderType.VERTEX,
    )
    for provider_type in provider_types:
        provider_models = by_provider[provider_type.value]
        defaults = DEFAULT_MODELS[provider_type]
        assert defaults["completion"] in provider_models
        assert defaults["completion_medium"] in provider_models


@pytest.mark.parametrize(
    ("provider_name", "expected"),
    [
        (" zhipu ", ProviderType.ZAI),
        ("open-router", ProviderType.OPENROUTER),
        ("kimi-for-coding", ProviderType.KIMI_CODING),
        ("volcano", ProviderType.VOLCENGINE),
        ("missing", None),
    ],
)
def test_provider_type_from_name_accepts_aliases(
    provider_name: str,
    expected: ProviderType | None,
) -> None:
    assert provider_type_from_name(provider_name) == expected


def test_detect_provider_name_from_env_uses_first_known_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, _provider_name in PROVIDER_AUTO_DETECT:
        monkeypatch.delenv(key, raising=False)

    assert detect_provider_name_from_env(default_provider="openai") == "openai"

    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert detect_provider_name_from_env(default_provider="openai") == "dashscope"


def test_resolve_provider_env_defaults_uses_env_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "ZAI_API_KEY",
        "ZHIPU_API_KEY",
        "ZAI_MODEL",
        "ZHIPU_MODEL",
        "ZAI_SMALL_MODEL",
        "ZAI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ZHIPU_API_KEY", " zhipu-key ")
    monkeypatch.setenv("ZAI_MODEL", " glm-custom ")
    monkeypatch.setenv("ZAI_SMALL_MODEL", " glm-small ")

    defaults = resolve_provider_env_defaults(ProviderType.ZAI)

    assert defaults.api_key == "zhipu-key"
    assert defaults.api_key_source == "ZHIPU_API_KEY"
    assert defaults.llm_model == "glm-custom"
    assert defaults.llm_model_source == "ZAI_MODEL"
    assert defaults.llm_small_model == "glm-small"
    assert defaults.llm_small_model_source == "ZAI_SMALL_MODEL"
    assert defaults.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert defaults.base_url_source is None
    assert defaults.api_key_env_vars == ("ZAI_API_KEY", "ZHIPU_API_KEY")


def test_resolve_provider_env_defaults_supports_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_SMALL_MODEL",
        "DEEPSEEK_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("DEEPSEEK_API_KEY", " deepseek-key ")
    monkeypatch.setenv("DEEPSEEK_MODEL", " deepseek-reasoner ")

    defaults = resolve_provider_env_defaults(ProviderType.DEEPSEEK)

    assert defaults.api_key == "deepseek-key"
    assert defaults.api_key_source == "DEEPSEEK_API_KEY"
    assert defaults.llm_model == "deepseek-reasoner"
    assert defaults.llm_model_source == "DEEPSEEK_MODEL"
    assert defaults.llm_small_model == "deepseek-v4-flash"
    assert defaults.base_url == "https://api.deepseek.com"
    assert defaults.api_key_env_vars == ("DEEPSEEK_API_KEY",)


def test_resolve_provider_env_defaults_uses_models_dev_env_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GEMINI_API_KEY",
        "MOONSHOT_API_KEY",
        "KIMI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", " google-key ")
    gemini = resolve_provider_env_defaults(ProviderType.GEMINI)
    assert gemini.api_key == "google-key"
    assert gemini.api_key_source == "GOOGLE_GENERATIVE_AI_API_KEY"
    assert gemini.embedding_model == "gemini-embedding-001"
    assert gemini.api_key_env_vars == (
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GEMINI_API_KEY",
    )

    monkeypatch.setenv("MOONSHOT_API_KEY", " moonshot-key ")
    kimi = resolve_provider_env_defaults(ProviderType.KIMI)
    assert kimi.api_key == "moonshot-key"
    assert kimi.api_key_source == "MOONSHOT_API_KEY"
    assert kimi.llm_model == "kimi-k2.5"
    assert kimi.llm_small_model == "kimi-k2.5"
    assert kimi.api_key_env_vars == ("MOONSHOT_API_KEY", "KIMI_API_KEY")


def test_resolve_provider_env_defaults_uses_models_dev_api_bases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("MINIMAX_API_KEY", "MINIMAX_BASE_URL"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("MINIMAX_API_KEY", " minimax-key ")

    defaults = resolve_provider_env_defaults(ProviderType.MINIMAX)

    assert defaults.api_key == "minimax-key"
    assert defaults.base_url == "https://api.minimax.io/anthropic/v1"


def test_resolve_provider_env_defaults_handles_unprofiled_provider() -> None:
    defaults = resolve_provider_env_defaults(ProviderType.MISTRAL)

    assert defaults.provider_type == ProviderType.MISTRAL
    assert defaults.api_key is None
    assert defaults.api_key_source is None
    assert defaults.api_key_env_vars == ()
