"""Single declaration of provider families, defaults, and static model rosters.

Security policy, environment resolution, LiteLLM prefixes, and the offline
model roster all read this module. Saved environment variable names stay
stable. Runtime defaults and environment-detection defaults are stored
separately where those two paths already disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.llm_providers.provider_env_profiles import ENV_PROFILES as _ENV_PROFILES, EnvProfile

_VARIANT_SUFFIXES: tuple[str, ...] = ("_coding", "_embedding", "_reranker")


@dataclass(frozen=True, slots=True)
class FamilySecurity:
    """Official endpoints and credential variable names for one provider family."""

    probe_base_url: str | None
    official_paths: tuple[str, ...]
    extra_origins: tuple[tuple[str, tuple[str, ...]], ...] = ()
    api_key_env_vars: tuple[str, ...] = ()
    local_http: bool = False
    probe_supported: bool = True
    persistent_auth: bool = True


@dataclass(frozen=True, slots=True)
class RuntimeModels:
    """Defaults used by the in-process LLM client when a model is omitted."""

    completion: str
    completion_medium: str
    embedding: str | None = None
    rerank: str | None = None


@dataclass(frozen=True, slots=True)
class StaticRoster:
    """Offline model IDs used when the models.dev snapshot has no rows."""

    chat: tuple[str, ...] = ()
    embedding: tuple[str, ...] = ()
    rerank: tuple[str, ...] = ()
    vision: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DetectionDefaults:
    """Non-secret defaults shown when scanning the process environment.

    Rerank stays unset unless the operator named a rerank model. That matches
    the historical startup detector, which must not invent a rerank provider.
    """

    llm_model: str
    llm_small_model: str
    embedding_model: str | None
    base_url: str | None


@dataclass(frozen=True, slots=True)
class LegacyLimits:
    """Limits for models that are absent from the models.dev snapshot."""

    context_window: int
    max_output_tokens: int
    input_budget_ratio: float | None = None
    chars_per_token: float | None = None


@dataclass(frozen=True, slots=True)
class TransportPrefix:
    """LiteLLM prefix member name plus whether the client should prepend it."""

    member: str
    prefix_model_names: bool


FAMILY_SECURITY: dict[str, FamilySecurity] = {
    "openai": FamilySecurity(
        "https://api.openai.com/v1", ("/v1",), api_key_env_vars=("OPENAI_API_KEY",)
    ),
    "openrouter": FamilySecurity(
        "https://openrouter.ai/api/v1",
        ("/api/v1",),
        api_key_env_vars=("OPENROUTER_API_KEY",),
    ),
    "dashscope": FamilySecurity(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ("/compatible-mode/v1",),
        api_key_env_vars=("DASHSCOPE_API_KEY",),
    ),
    "gemini": FamilySecurity(
        "https://generativelanguage.googleapis.com",
        ("", "/v1beta"),
        api_key_env_vars=("GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"),
    ),
    "anthropic": FamilySecurity(
        "https://api.anthropic.com",
        ("", "/v1"),
        api_key_env_vars=("ANTHROPIC_API_KEY",),
    ),
    "groq": FamilySecurity(
        "https://api.groq.com/openai/v1",
        ("/openai/v1",),
        api_key_env_vars=("GROQ_API_KEY",),
    ),
    "xai": FamilySecurity(
        "https://api.x.ai/v1",
        ("/v1",),
        extra_origins=(("us.api.x.ai", ("/v1",)),),
        api_key_env_vars=("XAI_API_KEY",),
    ),
    "mistral": FamilySecurity(
        "https://api.mistral.ai/v1",
        ("/v1",),
        api_key_env_vars=("MISTRAL_API_KEY",),
    ),
    "deepseek": FamilySecurity(
        "https://api.deepseek.com/v1",
        ("/v1",),
        api_key_env_vars=("DEEPSEEK_API_KEY",),
    ),
    "minimax": FamilySecurity(
        "https://api.minimax.io/v1",
        ("/v1",),
        api_key_env_vars=("MINIMAX_API_KEY",),
    ),
    "zai": FamilySecurity(
        "https://open.bigmodel.cn/api/paas/v4",
        ("/api/paas/v4",),
        api_key_env_vars=("ZAI_API_KEY", "ZHIPU_API_KEY"),
    ),
    "kimi": FamilySecurity(
        "https://api.moonshot.cn/v1",
        ("/v1",),
        extra_origins=(("api.kimi.com", ("/coding/v1",)),),
        api_key_env_vars=("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    ),
    "volcengine": FamilySecurity(
        "https://ark.cn-beijing.volces.com/api/v3",
        ("/api/v3",),
        api_key_env_vars=("VOLCENGINE_API_KEY", "ARK_API_KEY"),
    ),
    "cohere": FamilySecurity("https://api.cohere.com/v1", ("/v1",)),
    "ollama": FamilySecurity("http://localhost:11434", ("", "/api"), local_http=True),
    "lmstudio": FamilySecurity("http://localhost:1234/v1", ("/v1",), local_http=True),
    "azure_openai": FamilySecurity(None, (), probe_supported=False),
    "bedrock": FamilySecurity(None, (), probe_supported=False, persistent_auth=False),
    "vertex": FamilySecurity(None, (), probe_supported=False, persistent_auth=False),
}

RUNTIME_MODELS: dict[str, RuntimeModels] = {
    "openai": RuntimeModels("gpt-6-luna", "gpt-6-astra", "text-embedding-3-small", "gpt-6-luna"),
    "openrouter": RuntimeModels(
        "openai/gpt-6-luna",
        "openai/gpt-6-astra",
        "openai/text-embedding-3-small",
        "openai/gpt-6-luna",
    ),
    "anthropic": RuntimeModels(
        "claude-haiku-5-5",
        "claude-opus-5-5",
        "text-embedding-3-small",
        "claude-haiku-5-5",
    ),
    "gemini": RuntimeModels(
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-embedding-001",
        "gemini-3.6-flash",
    ),
    "dashscope": RuntimeModels(
        "qwen3.8-flash",
        "qwen3.8-max",
        "text-embedding-v3",
        "qwen3.8-flash",
    ),
    "kimi": RuntimeModels(
        "kimi-k3.1-pro-highspeed",
        "kimi-k3.1-pro",
        "kimi-embedding-1",
        "kimi-rerank-1",
    ),
    "deepseek": RuntimeModels(
        "deepseek-flash", "deepseek-v4-pro", "text-embedding-v3", "deepseek-flash"
    ),
    "minimax": RuntimeModels("MiniMax-M3.1-Flash", "MiniMax-M3", "embo-01", "MiniMax-M3.1-Flash"),
    "zai": RuntimeModels("glm-5.3-flash", "glm-5.3", "embedding-3", "glm-5.3-flash"),
    "mistral": RuntimeModels(
        "mistral-small-latest",
        "mistral-medium-latest",
        "mistral-embed",
        "mistral-small-latest",
    ),
    "groq": RuntimeModels(
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "text-embedding-3-small",
        "llama-3.1-8b-instant",
    ),
    "xai": RuntimeModels(
        "grok-4.20-0309-non-reasoning", "grok-4.7", None, "grok-4.20-0309-non-reasoning"
    ),
    "cohere": RuntimeModels(
        "command-a-03-2025",
        "command-a-plus-05-2026",
        "embed-english-v3.0",
        "rerank-english-v3.0",
    ),
    "ollama": RuntimeModels("llama3.1:8b", "llama3.1:70b", "nomic-embed-text", "llama3.1:8b"),
    "lmstudio": RuntimeModels(
        "local-model",
        "local-model",
        "text-embedding-nomic-embed-text-v1.5",
        "local-model",
    ),
    "bedrock": RuntimeModels(
        "anthropic.claude-haiku-5-5",
        "anthropic.claude-sonnet-5-5",
        "amazon.titan-embed-text-v1",
        "anthropic.claude-haiku-5-5",
    ),
    "vertex": RuntimeModels(
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "textembedding-gecko",
        "gemini-3.6-flash",
    ),
    "azure_openai": RuntimeModels(
        "gpt-6-luna", "gpt-6-astra", "text-embedding-3-small", "gpt-6-luna"
    ),
    "volcengine": RuntimeModels(
        "doubao-seed-2-0-lite-260428",
        "doubao-seed-2-1-pro-260628",
        "doubao-embedding-large",
        "doubao-reranker-large",
    ),
}

# primary, fast, embedding, rerank. ``None`` means that role has no suggested ID.
ROLE_DEFAULTS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    provider: (models.completion_medium, models.completion, models.embedding, models.rerank)
    for provider, models in RUNTIME_MODELS.items()
}
ROLE_DEFAULTS["xai"] = ("grok-4.7", "grok-4.20-0309-non-reasoning", None, None)

STATIC_ROSTER: dict[str, StaticRoster] = {
    "openai": StaticRoster(
        ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-4o", "gpt-4o-mini"),
        ("text-embedding-3-small", "text-embedding-3-large"),
    ),
    "openrouter": StaticRoster(
        (
            "openai/gpt-6-astra",
            "openai/gpt-6-luna",
            "anthropic/claude-opus-5.5",
            "openai/gpt-4o",
        ),
        ("openai/text-embedding-3-small",),
    ),
    "dashscope": StaticRoster(
        ("qwen3.8-max", "qwen3.8-flash", "qwen-max", "qwen-plus", "qwen-turbo"),
        ("text-embedding-v3", "text-embedding-v2"),
        ("qwen3-rerank",),
    ),
    "zai": StaticRoster(
        ("glm-5.3", "glm-5.3-flash", "glm-5.1", "glm-4.7-flash"),
        ("embedding-3", "embedding-2"),
    ),
    "kimi": StaticRoster(
        ("kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3", "kimi-k2.5"),
        ("kimi-embedding-1",),
        ("kimi-rerank-1",),
    ),
    "ollama": StaticRoster(
        ("llama3.1:8b", "qwen2.5:7b", "mistral-nemo"),
        ("nomic-embed-text",),
    ),
    "lmstudio": StaticRoster(("local-model",), ("text-embedding-nomic-embed-text-v1.5",)),
    "gemini": StaticRoster(
        ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-pro-preview", "gemini-2.5-flash"),
        ("gemini-embedding-001", "gemini-embedding-2"),
    ),
    "anthropic": StaticRoster(
        (
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
            "claude-fable-5-1",
            "claude-haiku-4-5",
        )
    ),
    "groq": StaticRoster(
        (
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "qwen/qwen3.8-27b",
        )
    ),
    "xai": StaticRoster(
        (
            "grok-4.7",
            "grok-4.6",
            "grok-4.20-0309-non-reasoning",
            "grok-4.20-0309-reasoning",
            "grok-build-0.1",
            "grok-imagine-image-2.0",
        )
    ),
    "deepseek": StaticRoster(
        ("deepseek-v4-pro", "deepseek-flash", "deepseek-chat", "deepseek-reasoner")
    ),
    "minimax": StaticRoster(
        ("MiniMax-M3", "MiniMax-M3.1-Flash", "MiniMax-M2.5", "MiniMax-M2.5-highspeed"),
        ("embo-01",),
    ),
    "cohere": StaticRoster(
        ("command-a-plus-05-2026", "command-a-03-2025", "command-r-plus-08-2024"),
        ("embed-english-v3.0", "embed-multilingual-v3.0"),
        ("rerank-english-v3.0", "rerank-multilingual-v3.0"),
    ),
    "mistral": StaticRoster(
        ("mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"),
        ("mistral-embed",),
    ),
    "azure_openai": StaticRoster(
        ("gpt-6-astra", "gpt-6-luna", "gpt-4o", "gpt-4o-mini"),
        ("text-embedding-3-small", "text-embedding-ada-002"),
    ),
    "bedrock": StaticRoster(
        (
            "anthropic.claude-opus-5-5",
            "anthropic.claude-sonnet-5-5",
            "anthropic.claude-haiku-5-5",
            "anthropic.claude-sonnet-4-6",
        ),
        ("amazon.titan-embed-text-v1", "amazon.titan-embed-text-v2:0"),
    ),
    "vertex": StaticRoster(
        ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-pro-preview"),
        ("textembedding-gecko", "gemini-embedding-001"),
    ),
    "volcengine": StaticRoster(
        (
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-turbo-260628",
            "doubao-seed-2-0-lite-260428",
            "doubao-seed-2-0-mini-260428",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-2.0-mini",
            "doubao-seed-2.0-code",
        ),
        (
            "doubao-embedding",
            "doubao-embedding-large",
            "doubao-embedding-large-text-240915",
            "doubao-embedding-large-text-250515",
            "doubao-embedding-text-240715",
        ),
        ("doubao-reranker-large",),
        ("doubao-1.5-vision-pro-32k", "doubao-seed-1-6-vision-250815"),
    ),
}

TRANSPORT_PREFIX: dict[str, TransportPrefix] = {
    "openai": TransportPrefix("OPENAI", False),
    "openrouter": TransportPrefix("OPENAI", True),
    "anthropic": TransportPrefix("ANTHROPIC", True),
    "gemini": TransportPrefix("GEMINI", True),
    "dashscope": TransportPrefix("DASHSCOPE", True),
    "deepseek": TransportPrefix("DEEPSEEK", True),
    "minimax": TransportPrefix("MINIMAX", True),
    "zai": TransportPrefix("ZAI", True),
    "kimi": TransportPrefix("KIMI", False),
    "mistral": TransportPrefix("MISTRAL", True),
    "groq": TransportPrefix("GROQ", True),
    "xai": TransportPrefix("XAI", True),
    "cohere": TransportPrefix("COHERE", True),
    "bedrock": TransportPrefix("BEDROCK", True),
    "vertex": TransportPrefix("VERTEX_AI", True),
    "azure_openai": TransportPrefix("AZURE", False),
    "ollama": TransportPrefix("OLLAMA", True),
    "lmstudio": TransportPrefix("LMSTUDIO", False),
    "volcengine": TransportPrefix("VOLCENGINE", True),
}

MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("qwen-", "dashscope"),
    ("qwq-", "dashscope"),
    ("gpt-", "openai"),
    ("o1-", "openai"),
    ("gemini-", "gemini"),
    ("deepseek-", "deepseek"),
    ("minimax-", "minimax"),
    ("abab", "minimax"),
    ("glm-", "zai"),
    ("grok-", "xai"),
    ("claude-", "anthropic"),
    ("mistral-", "mistral"),
    ("codestral-", "mistral"),
    ("rerank-", "cohere"),
    ("embed-", "openai"),
    ("text-embedding-", "openai"),
    ("doubao-", "volcengine"),
)

ENV_ALIASES: dict[str, str] = {
    "gemini": "gemini",
    "dashscope": "dashscope",
    "openai": "openai",
    "openrouter": "openrouter",
    "open-router": "openrouter",
    "deepseek": "deepseek",
    "minimax": "minimax",
    "minimax_coding": "minimax_coding",
    "minimax-coding": "minimax_coding",
    "minimax-coding-plan": "minimax_coding",
    "minimax_embedding": "minimax_embedding",
    "minimax-embedding": "minimax_embedding",
    "minimax_reranker": "minimax_reranker",
    "minimax-reranker": "minimax_reranker",
    "zai": "zai",
    "zhipu": "zai",
    "zai_coding": "zai_coding",
    "zai-coding": "zai_coding",
    "zai-coding-plan": "zai_coding",
    "zhipuai-coding-plan": "zai_coding",
    "zai_embedding": "zai_embedding",
    "zai-embedding": "zai_embedding",
    "zai_reranker": "zai_reranker",
    "zai-reranker": "zai_reranker",
    "kimi": "kimi",
    "moonshot": "kimi",
    "kimi_coding": "kimi_coding",
    "kimi-coding": "kimi_coding",
    "kimi-for-coding": "kimi_coding",
    "kimi_embedding": "kimi_embedding",
    "kimi-embedding": "kimi_embedding",
    "kimi_reranker": "kimi_reranker",
    "kimi-reranker": "kimi_reranker",
    "dashscope_coding": "dashscope_coding",
    "dashscope-coding": "dashscope_coding",
    "alibaba-cn": "dashscope_coding",
    "dashscope_embedding": "dashscope_embedding",
    "dashscope-embedding": "dashscope_embedding",
    "dashscope_reranker": "dashscope_reranker",
    "dashscope-reranker": "dashscope_reranker",
    "xai": "xai",
    "grok": "xai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "volcengine": "volcengine",
    "volcano": "volcengine",
    "ark": "volcengine",
    "doubao": "volcengine",
    "volcengine_coding": "volcengine_coding",
    "volcengine-coding": "volcengine_coding",
    "volcengine_embedding": "volcengine_embedding",
    "volcengine-embedding": "volcengine_embedding",
    "volcengine_reranker": "volcengine_reranker",
    "volcengine-reranker": "volcengine_reranker",
}

STARTUP_ALIASES: dict[str, str] = {
    "gemini": "gemini",
    "dashscope": "dashscope",
    "openai": "openai",
    "openrouter": "openrouter",
    "open-router": "openrouter",
    "deepseek": "deepseek",
    "minimax": "minimax",
    "zai": "zai",
    "zhipu": "zai",
    "kimi": "kimi",
    "moonshot": "kimi",
    "xai": "xai",
    "grok": "xai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "volcengine": "volcengine",
    "volcano": "volcengine",
    "ark": "volcengine",
    "doubao": "volcengine",
}

AUTO_DETECT_ENV: tuple[tuple[str, str], ...] = (
    ("GOOGLE_API_KEY", "gemini"),
    ("GOOGLE_GENERATIVE_AI_API_KEY", "gemini"),
    ("GEMINI_API_KEY", "gemini"),
    ("DASHSCOPE_API_KEY", "dashscope"),
    ("OPENAI_API_KEY", "openai"),
    ("OPENROUTER_API_KEY", "openrouter"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MINIMAX_API_KEY", "minimax"),
    ("ZAI_API_KEY", "zai"),
    ("ZHIPU_API_KEY", "zai"),
    ("MOONSHOT_API_KEY", "kimi"),
    ("KIMI_API_KEY", "kimi"),
    ("XAI_API_KEY", "xai"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OLLAMA_BASE_URL", "ollama"),
    ("LMSTUDIO_BASE_URL", "lmstudio"),
    ("VOLCENGINE_API_KEY", "volcengine"),
    ("ARK_API_KEY", "volcengine"),
)

DETECTION_DEFAULTS: dict[str, DetectionDefaults] = {
    "openai": DetectionDefaults("gpt-6-astra", "gpt-6-luna", "text-embedding-3-small", None),
    "openrouter": DetectionDefaults(
        "openai/gpt-6-astra",
        "openai/gpt-6-luna",
        "openai/text-embedding-3-small",
        "https://openrouter.ai/api/v1",
    ),
    "gemini": DetectionDefaults(
        "gemini-3.8-flash", "gemini-3.6-flash", "gemini-embedding-001", None
    ),
    "dashscope": DetectionDefaults(
        "qwen3.8-max",
        "qwen3.8-flash",
        "text-embedding-v3",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "deepseek": DetectionDefaults(
        "deepseek-v4-pro", "deepseek-flash", None, "https://api.deepseek.com/v1"
    ),
    "minimax": DetectionDefaults(
        "MiniMax-M3", "MiniMax-M3.1-Flash", "embo-01", "https://api.minimax.io/v1"
    ),
    "zai": DetectionDefaults(
        "glm-5.3", "glm-5.3-flash", "embedding-3", "https://open.bigmodel.cn/api/paas/v4"
    ),
    "kimi": DetectionDefaults(
        "kimi-k3.1-pro",
        "kimi-k3.1-pro-highspeed",
        "kimi-embedding-1",
        "https://api.moonshot.cn/v1",
    ),
    "xai": DetectionDefaults(
        "grok-4.7",
        "grok-4.20-0309-non-reasoning",
        None,
        "https://api.x.ai/v1",
    ),
    "anthropic": DetectionDefaults("claude-opus-5-5", "claude-haiku-5-5", "", None),
    "ollama": DetectionDefaults(
        "llama3.1:8b", "llama3.1:8b", "nomic-embed-text", "http://localhost:11434"
    ),
    "lmstudio": DetectionDefaults(
        "local-model",
        "local-model",
        "text-embedding-nomic-embed-text-v1.5",
        "http://localhost:1234/v1",
    ),
    "volcengine": DetectionDefaults(
        "doubao-seed-2-1-pro-260628",
        "doubao-seed-2-0-mini-260428",
        "doubao-embedding",
        "https://ark.cn-beijing.volces.com/api/v3",
    ),
}

LEGACY_MODEL_LIMITS: dict[str, LegacyLimits] = {
    "qwen-long": LegacyLimits(1_000_000, 8192, 0.9, 1.6),
    "deepseek-coder": LegacyLimits(65536, 8192),
    "glm-4": LegacyLimits(128_000, 4096),
    "glm-4-flash": LegacyLimits(128_000, 4096),
    "moonshot-v1-8k": LegacyLimits(8192, 8192),
    "moonshot-v1-32k": LegacyLimits(32768, 8192),
    "moonshot-v1-128k": LegacyLimits(131072, 8192),
}

ROLE_ORDER: tuple[str, ...] = ("primary", "fast", "embedding", "rerank", "voice")

_ENV_BY_TYPE: dict[str, EnvProfile] = {profile.provider_type: profile for profile in _ENV_PROFILES}


def provider_family(provider_type: object) -> str:
    """Normalize a provider type or enum to its base family."""
    normalized = str(getattr(provider_type, "value", provider_type)).strip().lower()
    for suffix in _VARIANT_SUFFIXES:
        if normalized.endswith(suffix):
            return normalized.removesuffix(suffix)
    return normalized


def family_security(provider_type: object) -> FamilySecurity | None:
    """Return official endpoint policy for a provider family."""
    return FAMILY_SECURITY.get(provider_family(provider_type))


def probe_default_base_urls() -> dict[str, str]:
    """Return canonical probe URLs for families that publish one."""
    return {
        family: spec.probe_base_url
        for family, spec in FAMILY_SECURITY.items()
        if spec.probe_base_url is not None
    }


def official_base_paths() -> dict[str, frozenset[str]]:
    """Return the exact API paths allowed on each official origin."""
    return {
        family: frozenset(spec.official_paths)
        for family, spec in FAMILY_SECURITY.items()
        if spec.probe_base_url is not None
    }


def extra_official_endpoints() -> dict[str, dict[str, frozenset[str]]]:
    """Return additional first-party origins and their allowed paths."""
    return {
        family: {host: frozenset(paths) for host, paths in spec.extra_origins}
        for family, spec in FAMILY_SECURITY.items()
        if spec.extra_origins
    }


def api_key_env_vars(provider_type: object) -> tuple[str, ...]:
    """Return credential variable names allowed for a provider family."""
    spec = family_security(provider_type)
    if spec is None:
        return ()
    return spec.api_key_env_vars


def runtime_model_table() -> dict[str, dict[str, str]]:
    """Return client defaults keyed by provider type and operation."""
    table: dict[str, dict[str, str]] = {}
    for provider_type, models in RUNTIME_MODELS.items():
        entry = {
            "completion": models.completion,
            "completion_medium": models.completion_medium,
        }
        if models.embedding is not None:
            entry["embedding"] = models.embedding
        if models.rerank is not None:
            entry["rerank"] = models.rerank
        table[provider_type] = entry
    return table


def role_defaults(provider_type: object) -> dict[str, str | None]:
    """Return suggested model IDs for primary, fast, embedding, and rerank."""
    family = provider_family(provider_type)
    primary, fast, embedding, rerank = ROLE_DEFAULTS.get(family, (None, None, None, None))
    return {
        "primary": primary,
        "fast": fast,
        "embedding": embedding,
        "rerank": rerank,
        "voice": None,
    }


def static_provider_models(provider_type: str) -> dict[str, list[str]]:
    """Return the offline roster for an exact provider type."""
    roster = STATIC_ROSTER.get(provider_type.strip().lower())
    if roster is None:
        return {}
    models = {
        "chat": list(roster.chat),
        "embedding": list(roster.embedding),
        "rerank": list(roster.rerank),
    }
    if roster.vision:
        models["vision"] = list(roster.vision)
    return models


def static_provider_models_document() -> dict[str, dict[str, list[str]]]:
    """Return the JSON document shared with the Rust runtimes."""
    return {provider_type: static_provider_models(provider_type) for provider_type in STATIC_ROSTER}


def env_profiles() -> tuple[EnvProfile, ...]:
    """Return environment profiles in their historical resolution order."""
    return _ENV_PROFILES


def env_profile(provider_type: object) -> EnvProfile | None:
    """Return the environment profile for one provider type value."""
    return _ENV_BY_TYPE.get(str(getattr(provider_type, "value", provider_type)))


def detection_defaults(provider_name: str) -> DetectionDefaults | None:
    """Return startup auto-fill defaults for a canonical provider name."""
    return DETECTION_DEFAULTS.get(provider_name)


def model_prefix_pairs() -> tuple[tuple[str, str], ...]:
    """Return model-name prefixes used to infer a provider type."""
    return MODEL_PREFIXES


def transport_prefix(provider_type: object) -> TransportPrefix | None:
    """Return the LiteLLM prefix for a base provider type."""
    return TRANSPORT_PREFIX.get(str(getattr(provider_type, "value", provider_type)))
