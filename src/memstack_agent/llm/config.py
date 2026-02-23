"""LLM configuration for memstack-agent.

Provides immutable configuration classes for LLM clients.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, kw_only=True)
class LLMConfig:
    """Immutable LLM configuration.

    Attributes:
        model: Model identifier (e.g., "claude-3-sonnet", "gpt-4")
        api_key: Optional API key (can also be set via environment)
        base_url: Optional base URL for API
        temperature: Sampling temperature (0.0 to 2.0)
        max_tokens: Maximum tokens in response
        top_p: Top-p sampling (0.0 to 1.0)
        timeout_seconds: Request timeout
    """

    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096
    top_p: float = 1.0
    timeout_seconds: int = 120

    def with_model(self, model: str) -> "LLMConfig":
        """Return new config with different model."""
        return LLMConfig(
            model=model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            timeout_seconds=self.timeout_seconds,
        )

    def with_temperature(self, temperature: float) -> "LLMConfig":
        """Return new config with different temperature."""
        return LLMConfig(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            timeout_seconds=self.timeout_seconds,
        )


# Preset configurations
def anthropic_config(model: str = "claude-3-sonnet-20240229", api_key: Optional[str] = None) -> LLMConfig:
    """Create Anthropic Claude configuration."""
    return LLMConfig(
        model=f"anthropic/{model}",
        api_key=api_key,
        temperature=0.0,
        max_tokens=4096,
    )


def openai_config(model: str = "gpt-4-turbo-preview", api_key: Optional[str] = None) -> LLMConfig:
    """Create OpenAI configuration."""
    return LLMConfig(
        model=f"openai/{model}",
        api_key=api_key,
        temperature=0.0,
        max_tokens=4096,
    )


def gemini_config(model: str = "gemini-pro", api_key: Optional[str] = None) -> LLMConfig:
    """Create Google Gemini configuration."""
    return LLMConfig(
        model=f"gemini/{model}",
        api_key=api_key,
        temperature=0.0,
        max_tokens=4096,
    )


def deepseek_config(model: str = "deepseek-chat", api_key: Optional[str] = None) -> LLMConfig:
    """Create DeepSeek configuration."""
    return LLMConfig(
        model=f"deepseek/{model}",
        api_key=api_key,
        temperature=0.0,
        max_tokens=4096,
    )


__all__ = [
    "LLMConfig",
    "anthropic_config",
    "openai_config",
    "gemini_config",
    "deepseek_config",
]
