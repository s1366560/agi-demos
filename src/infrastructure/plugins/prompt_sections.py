"""System prompt section capabilities (I2).

``system_prompt_section`` capabilities contribute text blocks that the
session processor merges into the per-step ``[Runtime Guidance]`` system
message. The builtin native-tool-protocol guidance is the reference row:
when the kernel registration is active it arrives through the registry;
otherwise the processor falls back to its hardcoded copy, so behavior is
identical in both worlds.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

from src.domain.model.plugins import CapabilityKind

from .context import CapabilityRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "NATIVE_TOOL_PROTOCOL_GUIDANCE",
    "NATIVE_TOOL_PROTOCOL_SECTION_ID",
    "collect_prompt_sections",
]

#: Capability id of the builtin native-tool-protocol guidance row.
NATIVE_TOOL_PROTOCOL_SECTION_ID = "native-tool-protocol"

#: Canonical text of the builtin guidance section. SessionProcessor keeps a
#: class-level alias for backward compatibility.
NATIVE_TOOL_PROTOCOL_GUIDANCE = (
    "When a tool is needed, use the runtime's native tool-call protocol and only "
    "the tools declared for the current step. Never print textual tool-call markup "
    "such as [TOOL_CALL]...[/TOOL_CALL], JSON/function-call stubs, or shell command "
    "code blocks as a substitute for calling a tool. Also never print "
    "<minimax:tool_call> or <invoke name=...> markup."
)


def collect_prompt_sections(registry: CapabilityRegistry) -> tuple[str, ...]:
    """Collect rendered section texts from all registered prompt capabilities.

    Supported implementation shapes: a plain string, an object exposing a
    ``text`` attribute, or a zero-arg callable returning a string. Invalid
    rows are skipped with a warning; they never fail prompt assembly.
    """
    sections: list[str] = []
    for record in registry.list_capabilities():
        if record.kind != CapabilityKind.SYSTEM_PROMPT_SECTION:
            continue
        text = _render(record.implementation)
        if text:
            sections.append(text)
        else:
            logger.warning(
                "system_prompt_section %s from plugin %s rendered empty; skipped",
                record.capability_id,
                record.plugin_id,
            )
    return tuple(sections)


def _render(implementation: object) -> str | None:
    if isinstance(implementation, str):
        return implementation.strip() or None
    text_attr = getattr(implementation, "text", None)
    if isinstance(text_attr, str) and text_attr.strip():
        return text_attr.strip()
    if callable(implementation):
        try:
            rendered = cast(Callable[[], object], implementation)()
        except Exception:
            logger.warning("system_prompt_section callable raised; skipped", exc_info=True)
            return None
        if isinstance(rendered, str) and rendered.strip():
            return rendered.strip()
    return None
