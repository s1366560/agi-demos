"""Unit tests for system_prompt_section collection and processor merge (I2)."""

from __future__ import annotations

import pytest

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
    ProvidedCapability,
)
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
)
from src.infrastructure.plugins.compatibility import register_builtin_kernel_plugins
from src.infrastructure.plugins.context import CapabilityRegistry, PluginContext
from src.infrastructure.plugins.prompt_sections import (
    NATIVE_TOOL_PROTOCOL_GUIDANCE,
    collect_prompt_sections,
)
from src.infrastructure.plugins.runtime_host import (
    PlatformPluginRuntimeHost,
    set_platform_plugin_runtime_host,
)


def _register_section(
    registry: CapabilityRegistry,
    plugin_id: str,
    section_id: str,
    implementation: object,
) -> None:
    manifest = PluginManifest(
        schema_version=1,
        id=plugin_id,
        version="1.0.0",
        runtime=PluginRuntimeKind.PYTHON_TRUSTED,
        trust=PluginTrust.BUILTIN,
        provides=(
            ProvidedCapability(
                kind=CapabilityKind.SYSTEM_PROMPT_SECTION,
                id=section_id,
                contract=f"prompt-section:{section_id}",
            ),
        ),
    )
    context = PluginContext(registry, manifest)
    context.register_capability(CapabilityKind.SYSTEM_PROMPT_SECTION, section_id, implementation)


@pytest.mark.unit
class TestCollectPromptSections:
    def test_string_implementation(self) -> None:
        registry = CapabilityRegistry()
        _register_section(registry, "p1", "s1", "  Follow the protocol.  ")
        assert collect_prompt_sections(registry) == ("Follow the protocol.",)

    def test_text_attribute_and_callable(self) -> None:
        class _Section:
            text = "from attribute"

        registry = CapabilityRegistry()
        _register_section(registry, "p1", "s1", _Section())
        _register_section(registry, "p2", "s2", lambda: "from callable")
        assert collect_prompt_sections(registry) == ("from attribute", "from callable")

    def test_invalid_rows_are_skipped(self) -> None:
        registry = CapabilityRegistry()
        _register_section(registry, "p1", "s1", object())
        _register_section(registry, "p2", "s2", "")
        assert collect_prompt_sections(registry) == ()


@pytest.mark.unit
class TestProcessorPromptSectionMerge:
    def test_kernel_registration_exposes_builtin_section(self) -> None:
        from src.infrastructure.agent.plugins.registry import AgentPluginRegistry

        registry = CapabilityRegistry()
        register_builtin_kernel_plugins(registry, AgentPluginRegistry())
        assert NATIVE_TOOL_PROTOCOL_GUIDANCE in collect_prompt_sections(registry)

    def test_processor_merges_sections_without_duplicating_guidance(self) -> None:
        host = PlatformPluginRuntimeHost()
        _register_section(
            host.capabilities, "p1", "native-tool-protocol", NATIVE_TOOL_PROTOCOL_GUIDANCE
        )
        set_platform_plugin_runtime_host(host)
        try:
            processor = SessionProcessor(config=ProcessorConfig(model="m"), tools=[])
            processor._session_instructions = []
            processor._response_instructions = []
            processor._merge_prompt_sections()
            message = processor._build_runtime_guidance_message()
            assert message is not None
            assert message["content"].count("native tool-call protocol") == 1
        finally:
            set_platform_plugin_runtime_host(None)

    def test_processor_fallback_is_byte_identical_without_registry(self) -> None:
        set_platform_plugin_runtime_host(None)
        try:
            processor = SessionProcessor(config=ProcessorConfig(model="m"), tools=[])
            processor._session_instructions = ["keep me"]
            processor._response_instructions = []
            processor._merge_prompt_sections()
            message = processor._build_runtime_guidance_message()
            assert message is not None
            assert "keep me" in message["content"]
            assert message["content"].count("native tool-call protocol") == 1
        finally:
            set_platform_plugin_runtime_host(None)
