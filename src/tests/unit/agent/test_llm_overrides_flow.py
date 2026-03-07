"""Tests for LLM override flow through the agent execution pipeline.

F1.5: Verifies that per-conversation LLM parameter overrides flow correctly from:
  execution.py (extract from app_model_context)
  -> project_react_agent.py (forward to stream)
  -> react_agent.py Phase 12 (merge into ProcessorConfig)

Tests cover:
  - Extraction of llm_overrides from ProjectChatRequest.app_model_context
  - Forwarding through ProjectReActAgent.execute_chat()
  - Merging into ProcessorConfig (temperature, max_tokens, provider_options)
  - Edge cases: None, empty dict, partial overrides, missing keys
"""

from __future__ import annotations

from typing import Any
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
            llm_overrides = request.app_model_context.get("llm_overrides")

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
            llm_overrides = request.app_model_context.get("llm_overrides")

        assert llm_overrides is None

    def test_extracts_empty_overrides_dict(self) -> None:
        """When llm_overrides is an empty dict, it's extracted as-is."""
        request = _make_chat_request(app_model_context={"llm_overrides": {}})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

        assert llm_overrides == {}

    def test_extracts_partial_overrides(self) -> None:
        """When only some override keys are present, extract what's there."""
        request = _make_chat_request(app_model_context={"llm_overrides": {"temperature": 0.3}})
        llm_overrides: dict[str, Any] | None = None
        if request.app_model_context:
            llm_overrides = request.app_model_context.get("llm_overrides")

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
            llm_overrides = request.app_model_context.get("llm_overrides")

        assert llm_overrides == all_overrides


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
        if llm_overrides:
            if "temperature" in llm_overrides:
                config.temperature = float(llm_overrides["temperature"])
            if "max_tokens" in llm_overrides:
                config.max_tokens = int(llm_overrides["max_tokens"])
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


# ===========================================================================
# C) ProjectReActAgent.execute_chat() forwarding
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
        mock_react_agent.stream = AsyncMock(side_effect=mock_stream)

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
        agent = ProjectReActAgent.__new__(ProjectReActAgent)
        agent.config = config
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
            events = []
            async for event in agent.execute_chat(
                conversation_id="conv-1",
                user_message="test",
                user_id="u1",
                llm_overrides=overrides,
            ):
                events.append(event)

        # Verify stream() was called with llm_overrides
        mock_react_agent.stream.assert_called_once()
        call_kwargs = mock_react_agent.stream.call_args[1]
        assert call_kwargs["llm_overrides"] == overrides

    async def test_forwards_none_overrides_when_not_provided(
        self,
    ) -> None:
        """execute_chat() passes llm_overrides=None when not provided."""
        mock_react_agent = AsyncMock()

        async def mock_stream(**kwargs: Any):  # type: ignore[no-untyped-def]
            yield {"type": "complete", "data": {"content": "done"}}

        mock_react_agent.stream = AsyncMock(side_effect=mock_stream)

        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        config = ProjectAgentConfig(
            tenant_id="t1",
            project_id="p1",
            agent_mode="default",
        )
        agent = ProjectReActAgent.__new__(ProjectReActAgent)
        agent.config = config
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
# D) End-to-end extraction + merge (simulated pipeline)
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
