"""P2-19: ToolDefinition.aliases-driven canonicalization in SessionProcessor.

These tests pin the contract that runtime tool-name resolution consults
``ToolDefinition.aliases`` rather than a module-level lookup table.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.agent.processor.processor import SessionProcessor, ToolDefinition


def _make_tool(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
) -> ToolDefinition:
    async def _execute(**_: Any) -> Any:  # pragma: no cover - never invoked
        return None

    return ToolDefinition(
        name=name,
        description=f"Tool: {name}",
        parameters={"type": "object", "properties": {}},
        execute=_execute,
        aliases=aliases,
    )


@pytest.fixture
def processor_with_tools() -> SessionProcessor:
    tools = {
        "memory_search": _make_tool("memory_search", aliases=("memorysearch",)),
        "memory_get": _make_tool("memory_get", aliases=("memoryget",)),
        "web_search": _make_tool("web_search"),
    }
    proc = SessionProcessor.__new__(SessionProcessor)
    proc.tools = tools  # type: ignore[attr-defined]
    return proc


@pytest.mark.unit
def test_canonicalize_exact_match_passthrough(processor_with_tools: SessionProcessor) -> None:
    assert processor_with_tools._canonicalize_tool_name("memory_search") == "memory_search"


@pytest.mark.unit
def test_canonicalize_casefold_match(processor_with_tools: SessionProcessor) -> None:
    assert processor_with_tools._canonicalize_tool_name("Memory_Search") == "memory_search"
    assert processor_with_tools._canonicalize_tool_name("WEB_SEARCH") == "web_search"


@pytest.mark.unit
def test_canonicalize_alias_resolution(processor_with_tools: SessionProcessor) -> None:
    # Alias declared on ToolDefinition.aliases resolves to canonical name.
    assert processor_with_tools._canonicalize_tool_name("memorysearch") == "memory_search"
    assert processor_with_tools._canonicalize_tool_name("MemorySearch") == "memory_search"
    assert processor_with_tools._canonicalize_tool_name("memoryget") == "memory_get"


@pytest.mark.unit
def test_canonicalize_compact_match_against_canonical(
    processor_with_tools: SessionProcessor,
) -> None:
    # Compact (alphanumeric-only) form matches against the canonical name itself.
    assert processor_with_tools._canonicalize_tool_name("memory-search") == "memory_search"
    assert processor_with_tools._canonicalize_tool_name("memory search") == "memory_search"


@pytest.mark.unit
def test_canonicalize_unknown_tool_passthrough(
    processor_with_tools: SessionProcessor,
) -> None:
    assert processor_with_tools._canonicalize_tool_name("does_not_exist") == "does_not_exist"


@pytest.mark.unit
def test_canonicalize_empty_passthrough(processor_with_tools: SessionProcessor) -> None:
    assert processor_with_tools._canonicalize_tool_name("") == ""


@pytest.mark.unit
def test_tool_definition_aliases_default_is_empty_tuple() -> None:
    td = _make_tool("foo")
    assert td.aliases == ()


@pytest.mark.unit
def test_processor_module_no_longer_exposes_legacy_alias_table() -> None:
    """P2-19: the module-level _TOOL_NAME_ALIASES table has been retired."""
    import src.infrastructure.agent.processor.processor as processor_mod

    assert not hasattr(processor_mod, "_TOOL_NAME_ALIASES")
