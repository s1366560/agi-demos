"""Tests for LLM override flow through the agent execution pipeline.

F1.5: Verifies that per-conversation LLM parameter overrides flow correctly from:
  execution.py (extract from app_model_context)
  -> project_react_agent.py (forward to stream)
  -> react_agent.py Phase 12 (merge into ProcessorConfig)

Tests cover:
  - Extraction of llm_overrides from ProjectChatRequest.app_model_context
  - Extraction of llm_model_override from ProjectChatRequest.app_model_context
  - Forwarding through ProjectReActAgent.execute_chat()
  - Merging into ProcessorConfig (temperature, max_tokens, provider_options)
  - Edge cases: None, empty dict, partial overrides, missing keys
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.actor.types import ProjectChatRequest
from src.infrastructure.agent.processor.processor import ProcessorConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_request(
    app_model_context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ProjectChatRequest:
    """Build a minimal ProjectChatRequest for testing."""
    defaults: dict[str, Any] = {
        "conversation_id": "conv-test-123",
        "message_id": "msg-test-456",
        "user_message": "Hello",
        "user_id": "user-test-789",
    }
    defaults.update(kwargs)
    return ProjectChatRequest(app_model_context=app_model_context, **defaults)


def _make_processor_config(**overrides: Any) -> ProcessorConfig:
    """Build a minimal ProcessorConfig for testing."""
    defaults: dict[str, Any] = {
        "model": "test-model",
        "temperature": 0.7,
        "max_tokens": 4096,
        "provider_options": {},
    }
    defaults.update(overrides)
    return ProcessorConfig(**defaults)


# ===========================================================================
# A) Extraction from app_model_context (execution.py logic)
# ===========================================================================


@pytest.mark.unit
class TestLlmOverridesExtraction:
    """Test extraction of llm_overrides from ProjectChatRequest.app_model_context."""

    def test_extracts_overrides_from_app_model_context(self) -> None:
        """When app_model_context contains llm_overrides, they are extracted."""
        request = _make_chat_request(
            app_model_context={"llm_overrides": {"temperature": 0.5, "max_tokens": 2048}}
        )
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides is not None
        assert llm_overrides["temperature"] == 0.5
        assert llm_overrides["max_tokens"] == 2048

    def test_returns_none_when_app_model_context_is_none(self) -> None:
        """When app_model_context is None, llm_overrides stays None."""
        request = _make_chat_request(app_model_context=None)
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        assert llm_overrides is None

    def test_returns_none_when_no_llm_overrides_key(self) -> None:
        """When app_model_context exists but has no llm_overrides key."""
        request = _make_chat_request(app_model_context={"some_other_key": "value"})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides is None

    def test_extracts_empty_overrides_dict(self) -> None:
        """When llm_overrides is an empty dict, it's extracted as-is."""
        request = _make_chat_request(app_model_context={"llm_overrides": {}})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides == {}

    def test_extracts_partial_overrides(self) -> None:
        """When only some override keys are present, extract what's there."""
        request = _make_chat_request(app_model_context={"llm_overrides": {"temperature": 0.3}})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides == {"temperature": 0.3}

    def test_preserves_all_override_keys(self) -> None:
        """All supported override keys are preserved during extraction."""
        all_overrides = {
            "temperature": 0.5,
            "max_tokens": 1024,
            "top_p": 0.9,
            "frequency_penalty": 0.5,
            "presence_penalty": 0.3,
        }
        request = _make_chat_request(app_model_context={"llm_overrides": all_overrides})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides == all_overrides

    def test_ignores_non_dict_llm_overrides_payload(self) -> None:
        """Non-dict llm_overrides payloads are treated as absent."""
        request = _make_chat_request(app_model_context={"llm_overrides": ["temperature", 0.3]})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            raw_llm_overrides = request.app_model_context.get("llm_overrides")
            if isinstance(raw_llm_overrides, dict):
                llm_overrides = raw_llm_overrides

        assert llm_overrides is None

    def test_extracts_model_override_from_app_model_context(self) -> None:
        """Model override is extracted from app_model_context when provided."""
        request = _make_chat_request(app_model_context={"llm_model_override": "openai/gpt-4o-mini"})
        model_override: str | None = None
        if request.app_model_context:
            raw_model = request.app_model_context.get("llm_model_override")
            if isinstance(raw_model, str):
                normalized = raw_model.strip()
                if normalized:
                    model_override = normalized

        assert model_override == "openai/gpt-4o-mini"

    def test_ignores_blank_model_override(self) -> None:
        """Blank model override values are treated as absent."""
        request = _make_chat_request(app_model_context={"llm_model_override": "   "})
        model_override: str | None = None
        if request.app_model_context:
            raw_model = request.app_model_context.get("llm_model_override")
            if isinstance(raw_model, str):
                normalized = raw_model.strip()
                if normalized:
                    model_override = normalized

        assert model_override is None


# ===========================================================================
# B) ProcessorConfig merge logic (react_agent.py Phase 12)
# ===========================================================================


@pytest.mark.unit
class TestProcessorConfigMerge:
    """Test the Phase 12 merge logic: llm_overrides -> ProcessorConfig.

    This replicates the exact merge logic from react_agent.py lines 2306-2321
    to verify each parameter is correctly applied.
    """

    @staticmethod
    def _apply_overrides(
        config: ProcessorConfig,
        llm_overrides: dict[str, Any] | None,
    ) -> ProcessorConfig:
        """Replicate the exact merge logic from react_agent.py Phase 12."""
        if not llm_overrides:
            return config

        def _to_float(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _to_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        parsed_temperature = _to_float(llm_overrides.get("temperature"))
        if parsed_temperature is not None:
            config.temperature = parsed_temperature

        parsed_max_tokens = _to_int(llm_overrides.get("max_tokens"))
        if parsed_max_tokens is not None:
            config.max_tokens = parsed_max_tokens

        for override_key, provider_option_key in (
            ("top_p", "top_p"),
            ("frequency_penalty", "frequency_penalty"),
            ("presence_penalty", "presence_penalty"),
        ):
            parsed = _to_float(llm_overrides.get(override_key))
            if parsed is not None:
                config.provider_options[provider_option_key] = parsed
        return config

    def test_temperature_override(self) -> None:
        """Temperature is overridden on the config."""
        config = _make_processor_config(temperature=0.7)
        self._apply_overrides(config, {"temperature": 0.2})
        assert config.temperature == 0.2

    def test_max_tokens_override(self) -> None:
        """Max tokens is overridden on the config."""
        config = _make_processor_config(max_tokens=4096)
        self._apply_overrides(config, {"max_tokens": 1024})
        assert config.max_tokens == 1024

    def test_top_p_goes_to_provider_options(self) -> None:
        """top_p is stored in provider_options, not on config directly."""
        config = _make_processor_config()
        self._apply_overrides(config, {"top_p": 0.95})
        assert config.provider_options["top_p"] == 0.95

    def test_frequency_penalty_goes_to_provider_options(self) -> None:
        """frequency_penalty is stored in provider_options."""
        config = _make_processor_config()
        self._apply_overrides(config, {"frequency_penalty": 0.7})
        assert config.provider_options["frequency_penalty"] == 0.7

    def test_presence_penalty_goes_to_provider_options(self) -> None:
        """presence_penalty is stored in provider_options."""
        config = _make_processor_config()
        self._apply_overrides(config, {"presence_penalty": 0.4})
        assert config.provider_options["presence_penalty"] == 0.4

    def test_all_overrides_applied_together(self) -> None:
        """All override keys are applied simultaneously."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(
            config,
            {
                "temperature": 0.1,
                "max_tokens": 512,
                "top_p": 0.8,
                "frequency_penalty": 0.6,
                "presence_penalty": 0.2,
            },
        )
        assert config.temperature == 0.1
        assert config.max_tokens == 512
        assert config.provider_options["top_p"] == 0.8
        assert config.provider_options["frequency_penalty"] == 0.6
        assert config.provider_options["presence_penalty"] == 0.2

    def test_none_overrides_leaves_defaults(self) -> None:
        """None llm_overrides does not change any config values."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(config, None)
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.provider_options == {}

    def test_empty_overrides_leaves_defaults(self) -> None:
        """Empty dict llm_overrides does not change any config values."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(config, {})
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.provider_options == {}

    def test_partial_override_only_changes_specified_keys(self) -> None:
        """Only specified keys are changed; others remain at defaults."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(config, {"temperature": 0.3})
        assert config.temperature == 0.3
        assert config.max_tokens == 4096  # unchanged
        assert config.provider_options == {}  # unchanged

    def test_type_coercion_temperature_from_int(self) -> None:
        """Integer temperature values are coerced to float."""
        config = _make_processor_config()
        self._apply_overrides(config, {"temperature": 1})
        assert config.temperature == 1.0
        assert isinstance(config.temperature, float)

    def test_type_coercion_max_tokens_from_float(self) -> None:
        """Float max_tokens values are coerced to int."""
        config = _make_processor_config()
        self._apply_overrides(config, {"max_tokens": 2048.0})
        assert config.max_tokens == 2048
        assert isinstance(config.max_tokens, int)

    def test_unknown_keys_are_ignored(self) -> None:
        """Keys not in the override mapping are silently ignored."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(config, {"unknown_param": "value", "temperature": 0.5})
        assert config.temperature == 0.5
        assert "unknown_param" not in config.provider_options

    def test_preserves_existing_provider_options(self) -> None:
        """Existing provider_options are preserved when adding overrides."""
        config = _make_processor_config(provider_options={"reasoning_effort": "high"})
        self._apply_overrides(config, {"top_p": 0.9})
        assert config.provider_options["reasoning_effort"] == "high"
        assert config.provider_options["top_p"] == 0.9

    def test_zero_temperature_is_valid(self) -> None:
        """Temperature of 0.0 is a valid override (greedy decoding)."""
        config = _make_processor_config(temperature=0.7)
        self._apply_overrides(config, {"temperature": 0})
        assert config.temperature == 0.0

    def test_zero_frequency_penalty_is_valid(self) -> None:
        """Frequency penalty of 0.0 is a valid override (no penalty)."""
        config = _make_processor_config()
        self._apply_overrides(config, {"frequency_penalty": 0})
        assert config.provider_options["frequency_penalty"] == 0.0

    def test_invalid_values_are_ignored(self) -> None:
        """Malformed override values are ignored instead of crashing."""
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        self._apply_overrides(
            config,
            {
                "temperature": "not-a-number",
                "max_tokens": "NaN",
                "top_p": [],
                "frequency_penalty": {},
                "presence_penalty": object(),
            },
        )
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.provider_options == {}


# ===========================================================================
# C) Model override validation/apply logic (react_agent.py Phase 12)
# ===========================================================================


@dataclass
class _FakeReasoningConfig:
    provider_options: dict[str, Any]
    omit_temperature: bool
    use_max_completion_tokens: bool
    override_max_tokens: int | None


@pytest.mark.unit
class TestModelOverrideApplication:
    """Test model override guard and provider option rebuild behavior."""

    _PROVIDER_ALIASES: ClassVar[dict[str, str]] = {"azure_openai": "openai"}

    @classmethod
    def _normalize_provider(cls, provider: str | None) -> str | None:
        if provider is None:
            return None
        normalized = provider.strip().lower()
        if not normalized:
            return None
        if normalized.endswith("_coding"):
            normalized = normalized.removesuffix("_coding")
        return cls._PROVIDER_ALIASES.get(normalized, normalized)

    @classmethod
    def _infer_provider_from_model_name(cls, model_name: str | None) -> str | None:
        if model_name is None:
            return None
        normalized_model = model_name.strip()
        if not normalized_model or "/" not in normalized_model:
            return None
        provider_part = normalized_model.split("/", 1)[0]
        return cls._normalize_provider(provider_part)

    @classmethod
    def _apply_model_override(
        cls,
        config: ProcessorConfig,
        model_override: str | None,
        *,
        override_provider: str | None,
        current_provider: str | None,
        resolved_provider: str | None = None,
        reasoning_cfg: _FakeReasoningConfig | None = None,
        tenant_scoped: bool = False,
    ) -> ProcessorConfig:
        normalized_override = (model_override or "").strip() or None
        if not normalized_override:
            return config

        current_provider_norm = cls._normalize_provider(
            current_provider
        ) or cls._infer_provider_from_model_name(config.model)
        override_provider_norm = cls._normalize_provider(
            override_provider
        ) or cls._infer_provider_from_model_name(normalized_override)
        resolved_provider_norm = cls._normalize_provider(resolved_provider)

        if tenant_scoped:
            should_apply_override = resolved_provider_norm is not None
        else:
            should_apply_override = resolved_provider_norm is not None
            if not should_apply_override:
                should_apply_override = (
                    override_provider_norm is not None
                    and current_provider_norm is not None
                    and current_provider_norm == override_provider_norm
                )
        if not should_apply_override:
            return config

        config.model = normalized_override
        provider_options = dict(config.provider_options)
        for key in (
            "reasoning_effort",
            "thinking",
            "reasoning_split",
            "__omit_temperature",
            "__use_max_completion_tokens",
            "__override_max_tokens",
        ):
            provider_options.pop(key, None)
        if reasoning_cfg:
            provider_options.update(reasoning_cfg.provider_options)
            provider_options["__omit_temperature"] = reasoning_cfg.omit_temperature
            provider_options["__use_max_completion_tokens"] = (
                reasoning_cfg.use_max_completion_tokens
            )
            provider_options["__override_max_tokens"] = reasoning_cfg.override_max_tokens
        config.provider_options = provider_options
        return config

    def test_accepts_same_provider_override(self) -> None:
        """Same-provider override is applied to config.model."""
        config = _make_processor_config(model="gpt-4o")
        self._apply_model_override(
            config,
            "gpt-4.1-mini",
            override_provider="openai",
            current_provider="openai",
        )
        assert config.model == "gpt-4.1-mini"

    def test_rejects_cross_provider_override(self) -> None:
        """Cross-provider override is ignored without provider resolution."""
        config = _make_processor_config(model="gpt-4o")
        self._apply_model_override(
            config,
            "claude-3-5-haiku",
            override_provider="anthropic",
            current_provider="openai",
        )
        assert config.model == "gpt-4o"

    def test_accepts_cross_provider_override_when_provider_is_resolved(self) -> None:
        """Resolved provider allows cross-provider model override."""
        config = _make_processor_config(model="gpt-4o")
        self._apply_model_override(
            config,
            "claude-3-5-haiku",
            override_provider="anthropic",
            current_provider="openai",
            resolved_provider="anthropic",
        )
        assert config.model == "claude-3-5-haiku"

    def test_rejects_override_when_tenant_resolution_fails(self) -> None:
        """Tenant-scoped override fails closed when provider resolution cannot find a match."""
        config = _make_processor_config(model="gpt-4o")
        self._apply_model_override(
            config,
            "gpt-4.1-mini",
            override_provider="openai",
            current_provider="openai",
            resolved_provider=None,
            tenant_scoped=True,
        )
        assert config.model == "gpt-4o"

    def test_rejects_override_when_current_provider_cannot_be_inferred(self) -> None:
        """Unknown current provider fails closed and ignores override."""
        config = _make_processor_config(model="custom-unknown-model")
        self._apply_model_override(
            config,
            "gpt-4.1-mini",
            override_provider="openai",
            current_provider=None,
        )
        assert config.model == "custom-unknown-model"

    def test_accepts_override_when_current_provider_inferred_from_model_prefix(self) -> None:
        """Provider inference from model prefix keeps alias-compatible override working."""
        config = _make_processor_config(model="azure_openai/gpt-4o")
        self._apply_model_override(
            config,
            "openai/gpt-4.1-mini",
            override_provider=None,
            current_provider=None,
        )
        assert config.model == "openai/gpt-4.1-mini"

    def test_resets_reasoning_keys_before_apply(self) -> None:
        """Stale reasoning keys are removed when override is accepted."""
        config = _make_processor_config(
            model="gpt-4o",
            provider_options={
                "reasoning_effort": "high",
                "thinking": {"type": "enabled", "budget_tokens": 2048},
                "reasoning_split": {"enabled": True},
                "__omit_temperature": True,
                "__use_max_completion_tokens": True,
                "__override_max_tokens": 32000,
                "top_p": 0.8,
            },
        )
        self._apply_model_override(
            config,
            "gpt-4.1-mini",
            override_provider="openai",
            current_provider="openai",
        )
        assert "reasoning_effort" not in config.provider_options
        assert "thinking" not in config.provider_options
        assert "reasoning_split" not in config.provider_options
        assert "__omit_temperature" not in config.provider_options
        assert "__use_max_completion_tokens" not in config.provider_options
        assert "__override_max_tokens" not in config.provider_options
        assert config.provider_options["top_p"] == 0.8

    def test_applies_reasoning_config_from_override_model(self) -> None:
        """Reasoning options are rebuilt from the override model config."""
        config = _make_processor_config(
            model="gpt-4o",
            provider_options={"reasoning_effort": "high", "top_p": 0.9},
        )
        reasoning_cfg = _FakeReasoningConfig(
            provider_options={"reasoning_effort": "medium", "thinking": {"type": "enabled"}},
            omit_temperature=True,
            use_max_completion_tokens=True,
            override_max_tokens=16384,
        )
        self._apply_model_override(
            config,
            "gpt-4.1-mini",
            override_provider="openai",
            current_provider="openai",
            reasoning_cfg=reasoning_cfg,
        )
        assert config.provider_options["reasoning_effort"] == "medium"
        assert config.provider_options["thinking"] == {"type": "enabled"}
        assert config.provider_options["__omit_temperature"] is True
        assert config.provider_options["__use_max_completion_tokens"] is True
        assert config.provider_options["__override_max_tokens"] == 16384
        assert config.provider_options["top_p"] == 0.9


# ===========================================================================
# D) ProjectReActAgent.execute_chat() forwarding
# ===========================================================================


@pytest.mark.unit
class TestProjectReActAgentForwarding:
    """Test that ProjectReActAgent.execute_chat() forwards llm_overrides."""

    async def test_forwards_llm_overrides_to_react_agent_stream(
        self,
    ) -> None:
        """execute_chat() passes llm_overrides kwarg to ReActAgent.stream()."""
        # We mock the entire ReActAgent to capture the call
        mock_react_agent = AsyncMock()

        # Make stream() return an async iterator
        async def mock_stream(**kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"type": "complete", "data": {"content": "done"}}

        mock_react_agent.stream = mock_stream
        mock_react_agent.stream = MagicMock(side_effect=mock_stream)

        # Build a minimal ProjectReActAgent with mocked internals
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        config = ProjectAgentConfig(
            tenant_id="t1",
            project_id="p1",
            agent_mode="default",
        )
        agent = ProjectReActAgent(config)
        agent._react_agent = mock_react_agent
        agent._status = MagicMock()
        agent._status.active_chats = 0
        agent._status.is_executing = False
        agent._status.successful_chats = 0
        agent._status.failed_chats = 0
        agent._status.total_events = 0
        agent._status.last_activity_at = None
        agent._status.last_error = None
        agent._exec_lock = MagicMock()
        agent._exec_lock.__aenter__ = AsyncMock(return_value=None)
        agent._exec_lock.__aexit__ = AsyncMock(return_value=None)

        # Patch the guard check and finalizer
        agent._ensure_ready_for_chat = AsyncMock(return_value=None)
        agent._finalize_chat_execution = AsyncMock()

        # Patch websocket notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=None,
        ):
            overrides = {"temperature": 0.5, "max_tokens": 1024}
            plugin_generation = {
                "profile_id": "default-v2",
                "generation": 7,
                "digest": "a" * 64,
            }
            events = []
            async for event in agent.execute_chat(
                conversation_id="conv-1",
                user_message="test",
                user_id="u1",
                llm_overrides=overrides,
                plugin_generation=plugin_generation,
            ):
                events.append(event)

        # Verify stream() was called with llm_overrides
        mock_react_agent.stream.assert_called_once()
        call_kwargs = mock_react_agent.stream.call_args[1]
        assert call_kwargs["llm_overrides"] == overrides
        assert call_kwargs["plugin_generation"] == plugin_generation

    async def test_forwards_model_override_to_react_agent_stream(self) -> None:
        """execute_chat() forwards model_override kwarg to ReActAgent.stream()."""
        mock_react_agent = AsyncMock()

        async def mock_stream(**kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"type": "complete", "data": {"content": "done"}}

        mock_react_agent.stream = MagicMock(side_effect=mock_stream)

        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        config = ProjectAgentConfig(
            tenant_id="t1",
            project_id="p1",
            agent_mode="default",
        )
        agent = ProjectReActAgent(config)
        agent._react_agent = mock_react_agent
        agent._status = MagicMock()
        agent._status.active_chats = 0
        agent._status.is_executing = False
        agent._status.successful_chats = 0
        agent._status.failed_chats = 0
        agent._status.total_events = 0
        agent._status.last_activity_at = None
        agent._status.last_error = None
        agent._exec_lock = MagicMock()
        agent._exec_lock.__aenter__ = AsyncMock(return_value=None)
        agent._exec_lock.__aexit__ = AsyncMock(return_value=None)
        agent._ensure_ready_for_chat = AsyncMock(return_value=None)
        agent._finalize_chat_execution = AsyncMock()

        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=None,
        ):
            async for _ in agent.execute_chat(
                conversation_id="conv-1",
                user_message="test",
                user_id="u1",
                model_override="openai/gpt-4o-mini",
            ):
                pass

        call_kwargs = mock_react_agent.stream.call_args[1]
        assert call_kwargs["model_override"] == "openai/gpt-4o-mini"

    async def test_forwards_none_overrides_when_not_provided(
        self,
    ) -> None:
        """execute_chat() passes llm_overrides=None when not provided."""
        mock_react_agent = AsyncMock()

        async def mock_stream(**kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"type": "complete", "data": {"content": "done"}}

        mock_react_agent.stream = MagicMock(side_effect=mock_stream)

        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        config = ProjectAgentConfig(
            tenant_id="t1",
            project_id="p1",
            agent_mode="default",
        )
        agent = ProjectReActAgent(config)
        agent._react_agent = mock_react_agent
        agent._status = MagicMock()
        agent._status.active_chats = 0
        agent._status.is_executing = False
        agent._status.successful_chats = 0
        agent._status.failed_chats = 0
        agent._status.total_events = 0
        agent._status.last_activity_at = None
        agent._status.last_error = None
        agent._exec_lock = MagicMock()
        agent._exec_lock.__aenter__ = AsyncMock(return_value=None)
        agent._exec_lock.__aexit__ = AsyncMock(return_value=None)
        agent._ensure_ready_for_chat = AsyncMock(return_value=None)
        agent._finalize_chat_execution = AsyncMock()

        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=None,
        ):
            events = []
            async for event in agent.execute_chat(
                conversation_id="conv-1",
                user_message="test",
                user_id="u1",
            ):
                events.append(event)

        call_kwargs = mock_react_agent.stream.call_args[1]
        assert call_kwargs.get("llm_overrides") is None


# ===========================================================================
# E) End-to-end extraction + merge (simulated pipeline)
# ===========================================================================


@pytest.mark.unit
class TestEndToEndOverrideFlow:
    """Simulate the full extraction-to-merge pipeline without real agents."""

    def test_full_pipeline_temperature_and_max_tokens(self) -> None:
        """Overrides flow from request through to ProcessorConfig."""
        # Step 1: Build request (frontend sends this)
        request = _make_chat_request(
            app_model_context={"llm_overrides": {"temperature": 0.3, "max_tokens": 2048}}
        )

        # Step 2: Extract (execution.py logic)
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        # Step 3: Merge into config (react_agent.py Phase 12 logic)
        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        if llm_overrides:
            if "temperature" in llm_overrides:
                config.temperature = float(llm_overrides["temperature"])
            if "max_tokens" in llm_overrides:
                config.max_tokens = int(llm_overrides["max_tokens"])

        # Step 4: Verify
        assert config.temperature == 0.3
        assert config.max_tokens == 2048

    def test_full_pipeline_provider_options(self) -> None:
        """Provider options (top_p, penalties) flow end to end."""
        request = _make_chat_request(
            app_model_context={
                "llm_overrides": {
                    "top_p": 0.9,
                    "frequency_penalty": 0.5,
                    "presence_penalty": 0.2,
                }
            }
        )

        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        config = _make_processor_config()
        if llm_overrides:
            if "top_p" in llm_overrides:
                config.provider_options["top_p"] = float(llm_overrides["top_p"])
            if "frequency_penalty" in llm_overrides:
                config.provider_options["frequency_penalty"] = float(
                    llm_overrides["frequency_penalty"]
                )
            if "presence_penalty" in llm_overrides:
                config.provider_options["presence_penalty"] = float(
                    llm_overrides["presence_penalty"]
                )

        assert config.provider_options["top_p"] == 0.9
        assert config.provider_options["frequency_penalty"] == 0.5
        assert config.provider_options["presence_penalty"] == 0.2

    def test_full_pipeline_no_overrides(self) -> None:
        """When no overrides are set, config remains at defaults."""
        request = _make_chat_request(app_model_context=None)

        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        if llm_overrides:
            if "temperature" in llm_overrides:
                config.temperature = float(llm_overrides["temperature"])
            if "max_tokens" in llm_overrides:
                config.max_tokens = int(llm_overrides["max_tokens"])

        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_full_pipeline_mixed_overrides_with_other_context(self) -> None:
        """llm_overrides coexist with other app_model_context keys."""
        request = _make_chat_request(
            app_model_context={
                "some_mcp_data": {"key": "value"},
                "llm_overrides": {"temperature": 0.1},
            }
        )

        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        config = _make_processor_config(temperature=0.7, max_tokens=4096)
        if llm_overrides:
            if "temperature" in llm_overrides:
                config.temperature = float(llm_overrides["temperature"])

        assert config.temperature == 0.1
        assert config.max_tokens == 4096  # unchanged
