"""Tool-name normalization helpers for policy allow/deny lists."""

from __future__ import annotations

from collections.abc import Iterable

_TOOL_NAME_ALIASES: dict[str, str] = {
    "bash": "bash",
    "edit": "edit",
    "glob": "glob",
    "grep": "grep",
    "multiedit": "edit",
    "read": "read",
    "readfile": "read",
    "todowrite": "todowrite",
    "todoread": "todoread",
    "webfetch": "web_scrape",
    "websearch": "web_search",
    "write": "write",
    "writefile": "write",
}


def canonical_tool_policy_name(name: str, known_tool_names: Iterable[str] | None = None) -> str:
    """Resolve user/agent-declared tool names to runtime tool identifiers.

    Agent definitions commonly use UI/Claude-style names such as ``Read`` or
    ``WebSearch`` while the runtime exposes snake_case names such as ``read`` and
    ``web_search``.  This helper keeps policy matching structural and
    deterministic while preserving unknown custom tool names.
    """

    raw = (name or "").strip()
    if not raw or raw == "*":
        return raw

    known = tuple(item for item in (known_tool_names or ()) if item)
    result = raw

    if raw in known:
        result = raw
    else:
        folded = raw.casefold()
        by_casefold = {item.casefold(): item for item in known}
        if folded in by_casefold:
            result = by_casefold[folded]
        else:
            compact = _compact_tool_name(raw)
            alias = _TOOL_NAME_ALIASES.get(compact)
            if alias:
                if not known or alias in known:
                    result = alias
                else:
                    alias_folded = alias.casefold()
                    if alias_folded in by_casefold:
                        result = by_casefold[alias_folded]

            if result == raw:
                by_compact = {_compact_tool_name(item): item for item in known}
                if compact in by_compact:
                    result = by_compact[compact]

    return result


def canonical_tool_policy_names(
    names: Iterable[str] | None,
    known_tool_names: Iterable[str] | None = None,
) -> list[str]:
    """Canonicalize a sequence of policy tool names while preserving order."""

    seen: set[str] = set()
    out: list[str] = []
    known = tuple(known_tool_names or ())
    for name in names or ():
        canonical = canonical_tool_policy_name(name, known)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _compact_tool_name(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())
