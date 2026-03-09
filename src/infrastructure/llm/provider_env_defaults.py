"""Provider environment auto-configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.domain.llm_providers.models import ProviderType


@dataclass(frozen=True)
class _EnvField:
    """Environment field config with candidate keys and fallback default."""

    env_vars: tuple[str, ...]
    default: str | None = None


@dataclass(frozen=True)
class _ProviderEnvProfile:
    """Environment profile for one provider type."""

    api_key: _EnvField
    llm_model: _EnvField
    llm_small_model: _EnvField = _EnvField(())
    embedding_model: _EnvField = _EnvField(())
    reranker_model: _EnvField = _EnvField(())
    base_url: _EnvField = _EnvField(())


@dataclass(frozen=True)
class ProviderEnvDefaults:
    """Resolved provider defaults from environment variables."""

    provider_type: ProviderType
    api_key: str | None
    api_key_source: str | None
    base_url: str | None
    base_url_source: str | None
    llm_model: str | None
    llm_model_source: str | None
    llm_small_model: str | None
    llm_small_model_source: str | None
    embedding_model: str | None
    embedding_model_source: str | None
    reranker_model: str | None
    reranker_model_source: str | None
    api_key_env_vars: tuple[str, ...]


PROVIDER_TYPE_MAP: dict[str, ProviderType] = {
    "gemini": ProviderType.GEMINI,
    "dashscope": ProviderType.DASHSCOPE,
    "openai": ProviderType.OPENAI,
    "openrouter": ProviderType.OPENROUTER,
    "open-router": ProviderType.OPENROUTER,
    "deepseek": ProviderType.DEEPSEEK,
    "minimax": ProviderType.MINIMAX,
    "minimax_coding": ProviderType.MINIMAX_CODING,
    "minimax-coding": ProviderType.MINIMAX_CODING,
    "minimax-coding-plan": ProviderType.MINIMAX_CODING,
    "minimax_embedding": ProviderType.MINIMAX_EMBEDDING,
    "minimax-embedding": ProviderType.MINIMAX_EMBEDDING,
    "minimax_reranker": ProviderType.MINIMAX_RERANKER,
    "minimax-reranker": ProviderType.MINIMAX_RERANKER,
    "zai": ProviderType.ZAI,
    "zhipu": ProviderType.ZAI,
    "zai_coding": ProviderType.ZAI_CODING,
    "zai-coding": ProviderType.ZAI_CODING,
    "zai-coding-plan": ProviderType.ZAI_CODING,
    "zhipuai-coding-plan": ProviderType.ZAI_CODING,
    "zai_embedding": ProviderType.ZAI_EMBEDDING,
    "zai-embedding": ProviderType.ZAI_EMBEDDING,
    "zai_reranker": ProviderType.ZAI_RERANKER,
    "zai-reranker": ProviderType.ZAI_RERANKER,
    "kimi": ProviderType.KIMI,
    "moonshot": ProviderType.KIMI,
    "kimi_coding": ProviderType.KIMI_CODING,
    "kimi-coding": ProviderType.KIMI_CODING,
    "kimi-for-coding": ProviderType.KIMI_CODING,
    "kimi_embedding": ProviderType.KIMI_EMBEDDING,
    "kimi-embedding": ProviderType.KIMI_EMBEDDING,
    "kimi_reranker": ProviderType.KIMI_RERANKER,
    "kimi-reranker": ProviderType.KIMI_RERANKER,
    "dashscope_coding": ProviderType.DASHSCOPE_CODING,
    "dashscope-coding": ProviderType.DASHSCOPE_CODING,
    "alibaba-cn": ProviderType.DASHSCOPE_CODING,
    "dashscope_embedding": ProviderType.DASHSCOPE_EMBEDDING,
    "dashscope-embedding": ProviderType.DASHSCOPE_EMBEDDING,
    "dashscope_reranker": ProviderType.DASHSCOPE_RERANKER,
    "dashscope-reranker": ProviderType.DASHSCOPE_RERANKER,
    "anthropic": ProviderType.ANTHROPIC,
    "claude": ProviderType.ANTHROPIC,
    "ollama": ProviderType.OLLAMA,
    "lmstudio": ProviderType.LMSTUDIO,
}

PROVIDER_AUTO_DETECT: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "gemini"),
    ("DASHSCOPE_API_KEY", "dashscope"),
    ("OPENAI_API_KEY", "openai"),
    ("OPENROUTER_API_KEY", "openrouter"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MINIMAX_API_KEY", "minimax"),
    ("ZAI_API_KEY", "zai"),
    ("ZHIPU_API_KEY", "zai"),
    ("KIMI_API_KEY", "kimi"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OLLAMA_BASE_URL", "ollama"),
    ("LMSTUDIO_BASE_URL", "lmstudio"),
]

_ENV_PROFILES: dict[ProviderType, _ProviderEnvProfile] = {
    ProviderType.GEMINI: _ProviderEnvProfile(
        api_key=_EnvField(("GEMINI_API_KEY",)),
        llm_model=_EnvField(("GEMINI_MODEL",), "gemini-2.0-flash"),
        embedding_model=_EnvField(("GEMINI_EMBEDDING_MODEL",), "text-embedding-004"),
        reranker_model=_EnvField(("GEMINI_RERANK_MODEL",), "gemini-2.0-flash"),
    ),
    ProviderType.ZAI: _ProviderEnvProfile(
        api_key=_EnvField(("ZAI_API_KEY", "ZHIPU_API_KEY")),
        llm_model=_EnvField(("ZAI_MODEL", "ZHIPU_MODEL"), "glm-4-plus"),
        llm_small_model=_EnvField(("ZAI_SMALL_MODEL", "ZHIPU_SMALL_MODEL"), "glm-4-flash"),
        embedding_model=_EnvField(("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL"), "embedding-3"),
        reranker_model=_EnvField(("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"), "glm-4-flash"),
        base_url=_EnvField(
            ("ZAI_BASE_URL", "ZHIPU_BASE_URL"),
            "https://open.bigmodel.cn/api/paas/v4",
        ),
    ),
    ProviderType.DASHSCOPE: _ProviderEnvProfile(
        api_key=_EnvField(("DASHSCOPE_API_KEY",)),
        llm_model=_EnvField(("DASHSCOPE_MODEL",), "qwen-plus"),
        llm_small_model=_EnvField(("DASHSCOPE_SMALL_MODEL",), "qwen-turbo"),
        embedding_model=_EnvField(("DASHSCOPE_EMBEDDING_MODEL",), "text-embedding-v3"),
        reranker_model=_EnvField(("DASHSCOPE_RERANK_MODEL",), "qwen-turbo"),
        base_url=_EnvField(
            ("DASHSCOPE_BASE_URL",),
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ),
    ProviderType.OPENAI: _ProviderEnvProfile(
        api_key=_EnvField(("OPENAI_API_KEY",)),
        llm_model=_EnvField(("OPENAI_MODEL",), "gpt-4o"),
        llm_small_model=_EnvField(("OPENAI_SMALL_MODEL",), "gpt-4o-mini"),
        embedding_model=_EnvField(("OPENAI_EMBEDDING_MODEL",), "text-embedding-3-small"),
        reranker_model=_EnvField(("OPENAI_RERANK_MODEL",), "gpt-4o-mini"),
        base_url=_EnvField(("OPENAI_BASE_URL",)),
    ),
    ProviderType.OPENROUTER: _ProviderEnvProfile(
        api_key=_EnvField(("OPENROUTER_API_KEY",)),
        llm_model=_EnvField(("OPENROUTER_MODEL",), "openai/gpt-4o"),
        llm_small_model=_EnvField(("OPENROUTER_SMALL_MODEL",), "openai/gpt-4o-mini"),
        embedding_model=_EnvField(("OPENROUTER_EMBEDDING_MODEL",), "openai/text-embedding-3-small"),
        reranker_model=_EnvField(("OPENROUTER_RERANK_MODEL",), "openai/gpt-4o-mini"),
        base_url=_EnvField(("OPENROUTER_BASE_URL",), "https://openrouter.ai/api/v1"),
    ),
    ProviderType.DEEPSEEK: _ProviderEnvProfile(
        api_key=_EnvField(("DEEPSEEK_API_KEY",)),
        llm_model=_EnvField(("DEEPSEEK_MODEL",), "deepseek-chat"),
        llm_small_model=_EnvField(("DEEPSEEK_SMALL_MODEL",), "deepseek-coder"),
        reranker_model=_EnvField(("DEEPSEEK_RERANK_MODEL",), "deepseek-chat"),
        base_url=_EnvField(("DEEPSEEK_BASE_URL",), "https://api.deepseek.com/v1"),
    ),
    ProviderType.MINIMAX: _ProviderEnvProfile(
        api_key=_EnvField(("MINIMAX_API_KEY",)),
        llm_model=_EnvField(("MINIMAX_MODEL",), "abab6.5-chat"),
        llm_small_model=_EnvField(("MINIMAX_SMALL_MODEL",), "abab6.5s-chat"),
        embedding_model=_EnvField(("MINIMAX_EMBEDDING_MODEL",), "embo-01"),
        reranker_model=_EnvField(("MINIMAX_RERANK_MODEL",), "abab6.5-chat"),
        base_url=_EnvField(("MINIMAX_BASE_URL",), "https://api.minimax.chat/v1"),
    ),
    ProviderType.MINIMAX_CODING: _ProviderEnvProfile(
        api_key=_EnvField(("MINIMAX_API_KEY",)),
        llm_model=_EnvField(("MINIMAX_CODING_MODEL", "MINIMAX_MODEL"), "MiniMax-M2.5"),
        llm_small_model=_EnvField(
            ("MINIMAX_CODING_SMALL_MODEL", "MINIMAX_SMALL_MODEL"),
            "MiniMax-M2.5-highspeed",
        ),
        embedding_model=_EnvField(("MINIMAX_EMBEDDING_MODEL",), "embo-01"),
        reranker_model=_EnvField(("MINIMAX_RERANK_MODEL",), "MiniMax-M2.5-highspeed"),
        base_url=_EnvField(
            ("MINIMAX_CODING_BASE_URL", "MINIMAX_BASE_URL"),
            "https://api.minimax.io/anthropic/v1",
        ),
    ),
    ProviderType.MINIMAX_EMBEDDING: _ProviderEnvProfile(
        api_key=_EnvField(("MINIMAX_API_KEY",)),
        llm_model=_EnvField(("MINIMAX_EMBEDDING_MODEL", "MINIMAX_MODEL"), "embo-01"),
        llm_small_model=_EnvField(("MINIMAX_EMBEDDING_SMALL_MODEL", "MINIMAX_SMALL_MODEL"), "embo-01"),
        embedding_model=_EnvField(("MINIMAX_EMBEDDING_MODEL",), "embo-01"),
        reranker_model=_EnvField(("MINIMAX_RERANK_MODEL",), "abab6.5-chat"),
        base_url=_EnvField(
            ("MINIMAX_EMBEDDING_BASE_URL", "MINIMAX_BASE_URL"),
            "https://api.minimax.chat/v1",
        ),
    ),
    ProviderType.MINIMAX_RERANKER: _ProviderEnvProfile(
        api_key=_EnvField(("MINIMAX_API_KEY",)),
        llm_model=_EnvField(("MINIMAX_RERANK_MODEL", "MINIMAX_MODEL"), "abab6.5-chat"),
        llm_small_model=_EnvField(("MINIMAX_RERANK_SMALL_MODEL", "MINIMAX_SMALL_MODEL"), "abab6.5-chat"),
        embedding_model=_EnvField(("MINIMAX_EMBEDDING_MODEL",), "embo-01"),
        reranker_model=_EnvField(("MINIMAX_RERANK_MODEL",), "abab6.5-chat"),
        base_url=_EnvField(
            ("MINIMAX_RERANK_BASE_URL", "MINIMAX_BASE_URL"),
            "https://api.minimax.chat/v1",
        ),
    ),
    ProviderType.KIMI: _ProviderEnvProfile(
        api_key=_EnvField(("KIMI_API_KEY",)),
        llm_model=_EnvField(("KIMI_MODEL",), "moonshot-v1-8k"),
        llm_small_model=_EnvField(("KIMI_SMALL_MODEL",), "moonshot-v1-8k"),
        embedding_model=_EnvField(("KIMI_EMBEDDING_MODEL",), "kimi-embedding-1"),
        reranker_model=_EnvField(("KIMI_RERANK_MODEL",), "kimi-rerank-1"),
        base_url=_EnvField(("KIMI_BASE_URL",), "https://api.moonshot.cn/v1"),
    ),
    ProviderType.KIMI_CODING: _ProviderEnvProfile(
        api_key=_EnvField(("KIMI_API_KEY",)),
        llm_model=_EnvField(("KIMI_CODING_MODEL", "KIMI_MODEL"), "kimi-k2-thinking"),
        llm_small_model=_EnvField(("KIMI_CODING_SMALL_MODEL", "KIMI_SMALL_MODEL"), "k2p5"),
        embedding_model=_EnvField(("KIMI_EMBEDDING_MODEL",), "kimi-embedding-1"),
        reranker_model=_EnvField(("KIMI_RERANK_MODEL",), "kimi-rerank-1"),
        base_url=_EnvField(
            ("KIMI_CODING_BASE_URL", "KIMI_BASE_URL"),
            "https://api.kimi.com/coding/v1",
        ),
    ),
    ProviderType.KIMI_EMBEDDING: _ProviderEnvProfile(
        api_key=_EnvField(("KIMI_API_KEY",)),
        llm_model=_EnvField(("KIMI_EMBEDDING_MODEL", "KIMI_MODEL"), "kimi-embedding-1"),
        llm_small_model=_EnvField(("KIMI_EMBEDDING_SMALL_MODEL", "KIMI_SMALL_MODEL"), "kimi-embedding-1"),
        embedding_model=_EnvField(("KIMI_EMBEDDING_MODEL",), "kimi-embedding-1"),
        reranker_model=_EnvField(("KIMI_RERANK_MODEL",), "kimi-rerank-1"),
        base_url=_EnvField(("KIMI_EMBEDDING_BASE_URL", "KIMI_BASE_URL"), "https://api.moonshot.cn/v1"),
    ),
    ProviderType.KIMI_RERANKER: _ProviderEnvProfile(
        api_key=_EnvField(("KIMI_API_KEY",)),
        llm_model=_EnvField(("KIMI_RERANK_MODEL", "KIMI_MODEL"), "kimi-rerank-1"),
        llm_small_model=_EnvField(("KIMI_RERANK_SMALL_MODEL", "KIMI_SMALL_MODEL"), "kimi-rerank-1"),
        embedding_model=_EnvField(("KIMI_EMBEDDING_MODEL",), "kimi-embedding-1"),
        reranker_model=_EnvField(("KIMI_RERANK_MODEL",), "kimi-rerank-1"),
        base_url=_EnvField(("KIMI_RERANK_BASE_URL", "KIMI_BASE_URL"), "https://api.moonshot.cn/v1"),
    ),
    ProviderType.ZAI_CODING: _ProviderEnvProfile(
        api_key=_EnvField(("ZAI_API_KEY", "ZHIPU_API_KEY")),
        llm_model=_EnvField(("ZAI_CODING_MODEL", "ZHIPU_CODING_MODEL", "ZAI_MODEL"), "glm-5"),
        llm_small_model=_EnvField(
            ("ZAI_CODING_SMALL_MODEL", "ZHIPU_CODING_SMALL_MODEL", "ZAI_SMALL_MODEL"),
            "glm-4.7-flash",
        ),
        embedding_model=_EnvField(("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL"), "embedding-3"),
        reranker_model=_EnvField(("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"), "glm-4.7-flash"),
        base_url=_EnvField(
            ("ZAI_CODING_BASE_URL", "ZHIPU_CODING_BASE_URL", "ZAI_BASE_URL", "ZHIPU_BASE_URL"),
            "https://api.z.ai/api/coding/paas/v4",
        ),
    ),
    ProviderType.ZAI_EMBEDDING: _ProviderEnvProfile(
        api_key=_EnvField(("ZAI_API_KEY", "ZHIPU_API_KEY")),
        llm_model=_EnvField(("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL", "ZAI_MODEL"), "embedding-3"),
        llm_small_model=_EnvField(
            ("ZAI_EMBEDDING_SMALL_MODEL", "ZHIPU_EMBEDDING_SMALL_MODEL", "ZAI_SMALL_MODEL"),
            "embedding-3",
        ),
        embedding_model=_EnvField(("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL"), "embedding-3"),
        reranker_model=_EnvField(("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"), "glm-4-flash"),
        base_url=_EnvField(
            ("ZAI_EMBEDDING_BASE_URL", "ZHIPU_EMBEDDING_BASE_URL", "ZAI_BASE_URL", "ZHIPU_BASE_URL"),
            "https://open.bigmodel.cn/api/paas/v4",
        ),
    ),
    ProviderType.ZAI_RERANKER: _ProviderEnvProfile(
        api_key=_EnvField(("ZAI_API_KEY", "ZHIPU_API_KEY")),
        llm_model=_EnvField(("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL", "ZAI_MODEL"), "glm-4-flash"),
        llm_small_model=_EnvField(
            ("ZAI_RERANK_SMALL_MODEL", "ZHIPU_RERANK_SMALL_MODEL", "ZAI_SMALL_MODEL"),
            "glm-4-flash",
        ),
        embedding_model=_EnvField(("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL"), "embedding-3"),
        reranker_model=_EnvField(("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"), "glm-4-flash"),
        base_url=_EnvField(
            ("ZAI_RERANK_BASE_URL", "ZHIPU_RERANK_BASE_URL", "ZAI_BASE_URL", "ZHIPU_BASE_URL"),
            "https://open.bigmodel.cn/api/paas/v4",
        ),
    ),
    ProviderType.DASHSCOPE_CODING: _ProviderEnvProfile(
        api_key=_EnvField(("DASHSCOPE_API_KEY",)),
        llm_model=_EnvField(("DASHSCOPE_CODING_MODEL", "DASHSCOPE_MODEL"), "qwen3-coder-plus"),
        llm_small_model=_EnvField(
            ("DASHSCOPE_CODING_SMALL_MODEL", "DASHSCOPE_SMALL_MODEL"),
            "qwen3-coder-flash",
        ),
        embedding_model=_EnvField(("DASHSCOPE_EMBEDDING_MODEL",), "text-embedding-v3"),
        reranker_model=_EnvField(("DASHSCOPE_RERANK_MODEL",), "qwen3-coder-flash"),
        base_url=_EnvField(
            ("DASHSCOPE_CODING_BASE_URL", "DASHSCOPE_BASE_URL"),
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ),
    ProviderType.DASHSCOPE_EMBEDDING: _ProviderEnvProfile(
        api_key=_EnvField(("DASHSCOPE_API_KEY",)),
        llm_model=_EnvField(("DASHSCOPE_EMBEDDING_MODEL", "DASHSCOPE_MODEL"), "text-embedding-v3"),
        llm_small_model=_EnvField(
            ("DASHSCOPE_EMBEDDING_SMALL_MODEL", "DASHSCOPE_SMALL_MODEL"),
            "text-embedding-v3",
        ),
        embedding_model=_EnvField(("DASHSCOPE_EMBEDDING_MODEL",), "text-embedding-v3"),
        reranker_model=_EnvField(("DASHSCOPE_RERANK_MODEL",), "qwen-turbo"),
        base_url=_EnvField(
            ("DASHSCOPE_EMBEDDING_BASE_URL", "DASHSCOPE_BASE_URL"),
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ),
    ProviderType.DASHSCOPE_RERANKER: _ProviderEnvProfile(
        api_key=_EnvField(("DASHSCOPE_API_KEY",)),
        llm_model=_EnvField(("DASHSCOPE_RERANK_MODEL", "DASHSCOPE_MODEL"), "qwen-turbo"),
        llm_small_model=_EnvField(("DASHSCOPE_RERANK_SMALL_MODEL", "DASHSCOPE_SMALL_MODEL"), "qwen-turbo"),
        embedding_model=_EnvField(("DASHSCOPE_EMBEDDING_MODEL",), "text-embedding-v3"),
        reranker_model=_EnvField(("DASHSCOPE_RERANK_MODEL",), "qwen-turbo"),
        base_url=_EnvField(
            ("DASHSCOPE_RERANK_BASE_URL", "DASHSCOPE_BASE_URL"),
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ),
    ProviderType.ANTHROPIC: _ProviderEnvProfile(
        api_key=_EnvField(("ANTHROPIC_API_KEY",)),
        llm_model=_EnvField(("ANTHROPIC_MODEL",), "claude-3-5-sonnet-20240620"),
        llm_small_model=_EnvField(("ANTHROPIC_SMALL_MODEL",), "claude-3-haiku-20240307"),
        embedding_model=_EnvField(("ANTHROPIC_EMBEDDING_MODEL",)),
        reranker_model=_EnvField(("ANTHROPIC_RERANK_MODEL",), "claude-3-haiku-20240307"),
        base_url=_EnvField(("ANTHROPIC_BASE_URL",)),
    ),
    ProviderType.OLLAMA: _ProviderEnvProfile(
        api_key=_EnvField(("OLLAMA_API_KEY",)),
        llm_model=_EnvField(("OLLAMA_MODEL",), "llama3.1:8b"),
        llm_small_model=_EnvField(("OLLAMA_SMALL_MODEL",), "llama3.1:8b"),
        embedding_model=_EnvField(("OLLAMA_EMBEDDING_MODEL",), "nomic-embed-text"),
        reranker_model=_EnvField(("OLLAMA_RERANK_MODEL",), "llama3.1:8b"),
        base_url=_EnvField(("OLLAMA_BASE_URL",), "http://localhost:11434"),
    ),
    ProviderType.LMSTUDIO: _ProviderEnvProfile(
        api_key=_EnvField(("LMSTUDIO_API_KEY",)),
        llm_model=_EnvField(("LMSTUDIO_MODEL",), "local-model"),
        llm_small_model=_EnvField(("LMSTUDIO_SMALL_MODEL",), "local-model"),
        embedding_model=_EnvField(
            ("LMSTUDIO_EMBEDDING_MODEL",),
            "text-embedding-nomic-embed-text-v1.5",
        ),
        reranker_model=_EnvField(("LMSTUDIO_RERANK_MODEL",), "local-model"),
        base_url=_EnvField(("LMSTUDIO_BASE_URL",), "http://localhost:1234/v1"),
    ),
}


def provider_type_from_name(provider_name: str) -> ProviderType | None:
    """Resolve provider alias/name to ProviderType."""
    normalized = provider_name.strip().lower()
    return PROVIDER_TYPE_MAP.get(normalized)


def detect_provider_name_from_env(default_provider: str = "gemini") -> str:
    """Auto-detect provider name from known environment variables."""
    for env_var, provider_name in PROVIDER_AUTO_DETECT:
        if os.getenv(env_var):
            return provider_name
    return default_provider


def _resolve_field(field: _EnvField) -> tuple[str | None, str | None]:
    for env_var in field.env_vars:
        raw_value = os.getenv(env_var)
        if raw_value and raw_value.strip():
            return raw_value.strip(), env_var
    if field.default is None:
        return None, None
    return field.default, None


def resolve_provider_env_defaults(provider_type: ProviderType) -> ProviderEnvDefaults:
    """Resolve provider defaults and API key from environment."""
    profile = _ENV_PROFILES.get(provider_type)
    if profile is None:
        return ProviderEnvDefaults(
            provider_type=provider_type,
            api_key=None,
            api_key_source=None,
            base_url=None,
            base_url_source=None,
            llm_model=None,
            llm_model_source=None,
            llm_small_model=None,
            llm_small_model_source=None,
            embedding_model=None,
            embedding_model_source=None,
            reranker_model=None,
            reranker_model_source=None,
            api_key_env_vars=(),
        )

    api_key, api_key_source = _resolve_field(profile.api_key)
    base_url, base_url_source = _resolve_field(profile.base_url)
    llm_model, llm_model_source = _resolve_field(profile.llm_model)
    llm_small_model, llm_small_model_source = _resolve_field(profile.llm_small_model)
    embedding_model, embedding_model_source = _resolve_field(profile.embedding_model)
    reranker_model, reranker_model_source = _resolve_field(profile.reranker_model)

    return ProviderEnvDefaults(
        provider_type=provider_type,
        api_key=api_key,
        api_key_source=api_key_source,
        base_url=base_url,
        base_url_source=base_url_source,
        llm_model=llm_model,
        llm_model_source=llm_model_source,
        llm_small_model=llm_small_model,
        llm_small_model_source=llm_small_model_source,
        embedding_model=embedding_model,
        embedding_model_source=embedding_model_source,
        reranker_model=reranker_model,
        reranker_model_source=reranker_model_source,
        api_key_env_vars=profile.api_key.env_vars,
    )
