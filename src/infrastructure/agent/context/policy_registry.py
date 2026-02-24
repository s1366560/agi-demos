"""Context policy registry for pluggable pre/post compression policies."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MessageList = list[dict[str, Any]]
PreCompressionPolicy = Callable[[MessageList], MessageList]
SummaryPolicy = Callable[[str, MessageList], str]

_FILE_PATH_RE = re.compile(r"(?:/|\.?/)?(?:[\w.-]+/)+[\w.-]+\.[\w-]+")
_FAILURE_HINT_RE = re.compile(r"\b(error|failed|exception|traceback|timeout)\b", re.IGNORECASE)


@dataclass
class ContextPolicyRegistry:
    """Registry for context policies applied during context building."""

    pre_compression: list[tuple[str, PreCompressionPolicy]] = field(default_factory=list)
    summary_enrichment: list[tuple[str, SummaryPolicy]] = field(default_factory=list)

    def register_pre_compression(self, name: str, policy: PreCompressionPolicy) -> None:
        self.pre_compression.append((name, policy))

    def register_summary_enrichment(self, name: str, policy: SummaryPolicy) -> None:
        self.summary_enrichment.append((name, policy))

    def apply_pre_compression(self, messages: MessageList) -> tuple[MessageList, dict[str, Any]]:
        current = list(messages)
        metadata: dict[str, Any] = {"applied": [], "errors": []}
        for name, policy in self.pre_compression:
            try:
                current = policy(current)
                metadata["applied"].append(name)
            except Exception as exc:
                logger.warning("[ContextPolicyRegistry] pre policy %s failed: %s", name, exc)
                metadata["errors"].append({"policy": name, "error": str(exc)})
        return current, metadata

    def apply_summary_enrichment(
        self,
        summary_text: str,
        messages: MessageList,
    ) -> tuple[str, dict[str, Any]]:
        current = summary_text
        metadata: dict[str, Any] = {"applied": [], "errors": []}
        for name, policy in self.summary_enrichment:
            try:
                current = policy(current, messages)
                metadata["applied"].append(name)
            except Exception as exc:
                logger.warning("[ContextPolicyRegistry] summary policy %s failed: %s", name, exc)
                metadata["errors"].append({"policy": name, "error": str(exc)})
        return current, metadata


def dedupe_cached_summary_messages(messages: MessageList) -> MessageList:
    """Keep only the newest cached-summary system message."""
    summary_indexes = [
        idx
        for idx, msg in enumerate(messages)
        if msg.get("role") == "system"
        and isinstance(msg.get("content"), str)
        and "[Previous conversation summary" in msg.get("content", "")
    ]
    if len(summary_indexes) <= 1:
        return messages

    keep_index = summary_indexes[-1]
    return [
        msg
        for idx, msg in enumerate(messages)
        if idx == keep_index or idx not in set(summary_indexes[:-1])
    ]


def enrich_summary_with_tool_failures(summary_text: str, messages: MessageList) -> str:
    """Append compact tool-failure highlights extracted from source messages."""
    failures: list[str] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not _FAILURE_HINT_RE.search(content):
            continue
        tool_name = str(msg.get("name") or "unknown")
        snippet = " ".join(content.strip().split())
        if len(snippet) > 140:
            snippet = snippet[:140] + "..."
        failures.append(f"- {tool_name}: {snippet}")
        if len(failures) >= 4:
            break

    if not failures:
        return summary_text
    return summary_text.rstrip() + "\n\n[Tool failure highlights]\n" + "\n".join(failures)


def enrich_summary_with_file_activity(summary_text: str, messages: MessageList) -> str:
    """Append referenced file paths to improve continuity across compaction."""
    found_paths: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        for match in _FILE_PATH_RE.findall(content):
            normalized = match.strip()
            if normalized and normalized not in found_paths:
                found_paths.append(normalized)
            if len(found_paths) >= 6:
                break
        if len(found_paths) >= 6:
            break

    if not found_paths:
        return summary_text
    items = "\n".join(f"- {path}" for path in found_paths)
    return summary_text.rstrip() + "\n\n[File activity]\n" + items
