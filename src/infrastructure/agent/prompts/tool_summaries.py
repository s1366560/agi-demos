"""
Enhanced tool summaries and presentation ordering.

Provides curated one-line descriptions for key tools that override
the default tool.description in the system prompt, plus a preferred
presentation order so the most important tools appear first.

Ported from OpenClaw's system-prompt.ts toolSummary() concept:
give the LLM richer, more actionable context about each tool than
the raw schema description alone.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TOOL_SUMMARIES
# ---------------------------------------------------------------------------
# Maps tool name -> enhanced description.
# When a tool's name appears here, convert_tools() will override its
# description with this value.  Tools NOT in this dict keep their
# original descriptions unchanged.
#
# Guidelines for writing summaries:
#  - One sentence, imperative mood ("Search ...", "Execute ...")
#  - State the primary action AND the typical use-case
#  - Mention key constraints (e.g. sandbox-only, requires API key)
#  - Keep under 120 characters
# ---------------------------------------------------------------------------

TOOL_SUMMARIES: dict[str, str] = {
    # --- Core Task Management ---
    "todoread": ("Read the current task list to check progress and pending items."),
    "todowrite": ("Create, update, or replace tasks in the task list to track work progress."),
    # --- Memory & Knowledge ---
    "memory_search": (
        "Search the knowledge graph for memories, entities, and relationships "
        "relevant to the current query."
    ),
    "memory_get": ("Retrieve a specific memory entry by its unique identifier."),
    "memory_create": (
        "Store a new memory in the knowledge graph for future retrieval and reasoning."
    ),
    # --- Terminal & Execution ---
    "terminal": (
        "Execute shell commands in the sandbox terminal for file operations, "
        "builds, tests, and system tasks."
    ),
    "desktop": (
        "Interact with the sandbox desktop environment for GUI automation and screenshots."
    ),
    # --- Web ---
    "web_search": ("Search the web for up-to-date information, documentation, and references."),
    "web_scrape": (
        "Fetch and extract content from a specific URL, returning cleaned text or HTML."
    ),
    # --- Human Interaction ---
    "clarification": (
        "Ask the user a clarifying question when the request is ambiguous or "
        "missing critical information."
    ),
    "decision": ("Present options to the user and request a decision before proceeding."),
    # --- Skill & Plugin ---
    "skill": ("Load a specific skill by name to gain specialized knowledge and instructions."),
    "skill_loader": ("List available skills or load a skill's full content for reference."),
    "skill_installer": (
        "Install a skill from a remote source (e.g. GitHub) into the local skill directory."
    ),
    "plugin_manager": ("Manage agent plugins: list, install, enable, disable, or reload plugins."),
    # --- SubAgent Delegation ---
    "delegate_to_subagent": ("Delegate a task to a specialized sub-agent with domain expertise."),
    "parallel_delegate_subagents": (
        "Delegate multiple independent tasks to sub-agents for parallel execution."
    ),
    "subagents": ("List available sub-agents with their capabilities and trigger patterns."),
    # --- Session Management ---
    "sessions_spawn": ("Spawn a new sub-agent session for ongoing multi-turn collaboration."),
    "sessions_list": ("List active and recent sub-agent sessions with status summaries."),
    "sessions_history": ("Retrieve the message history of a specific sub-agent session."),
    "sessions_send": ("Send a follow-up message to an existing sub-agent session."),
    "sessions_wait": ("Wait for one or more sub-agent sessions to complete before continuing."),
    "sessions_ack": ("Acknowledge and resolve a human-in-the-loop request from a sub-agent."),
    "sessions_timeline": ("View the event timeline of a sub-agent session for debugging."),
    "sessions_overview": ("Get an overview of all active sessions with resource utilization."),
    # --- Environment ---
    "get_env_var": ("Read an environment variable value from the sandbox runtime."),
    "request_env_var": ("Ask the user to provide a required environment variable (e.g. API key)."),
    "check_env_vars": ("Check availability of environment variables required by specific tools."),
    # --- MCP ---
    "register_mcp_server": ("Install, start, or discover tools from an MCP server in the sandbox."),
    "debug_mcp_server": (
        "Inspect MCP server status, logs, and available tools for troubleshooting."
    ),
    "create_mcp_server_from_template": (
        "Generate a new MCP server project from a built-in template."
    ),
}

# ---------------------------------------------------------------------------
# TOOL_ORDER
# ---------------------------------------------------------------------------
# Defines the preferred presentation order of tools in the system prompt.
# Tools listed here appear first (in this order); tools not listed are
# appended in their original order after the ordered set.
#
# Rationale:
#  1. Task management first — the agent should always track its work
#  2. Memory / knowledge — understand context before acting
#  3. Terminal / desktop — primary execution tools
#  4. Web research — gather information when needed
#  5. Human interaction — ask only when necessary
#  6. Delegation — farm out specialized work
#  7. Skill / plugin — extend capabilities
#  8. Environment / MCP — infrastructure
# ---------------------------------------------------------------------------

TOOL_ORDER: list[str] = [
    # Task management
    "todoread",
    "todowrite",
    # Memory & knowledge
    "memory_search",
    "memory_get",
    "memory_create",
    # Execution
    "terminal",
    "desktop",
    # Web
    "web_search",
    "web_scrape",
    # Human interaction
    "clarification",
    "decision",
    # SubAgent delegation
    "delegate_to_subagent",
    "parallel_delegate_subagents",
    "subagents",
    # Sessions
    "sessions_spawn",
    "sessions_send",
    "sessions_list",
    "sessions_history",
    "sessions_wait",
    "sessions_ack",
    "sessions_timeline",
    "sessions_overview",
    # Skills & plugins
    "skill",
    "skill_loader",
    "skill_installer",
    "plugin_manager",
    # Environment
    "get_env_var",
    "request_env_var",
    "check_env_vars",
    # MCP
    "register_mcp_server",
    "debug_mcp_server",
    "create_mcp_server_from_template",
]


def apply_tool_summaries(
    definitions: list[object],
    summaries: dict[str, str] | None = None,
) -> None:
    """Apply enhanced descriptions from *summaries* to tool definitions in-place.

    Args:
        definitions: List of ToolDefinition objects (must have ``name`` and
            ``description`` attributes).
        summaries: Mapping of tool name to enhanced description.
            Defaults to :data:`TOOL_SUMMARIES`.
    """
    if summaries is None:
        summaries = TOOL_SUMMARIES

    for defn in definitions:
        name = getattr(defn, "name", None)
        if name and name in summaries:
            object.__setattr__(defn, "description", summaries[name])


def sort_by_tool_order(
    definitions: list[object],
    order: list[str] | None = None,
) -> list[object]:
    """Return *definitions* sorted according to *order*.

    Tools whose name appears in *order* come first (in that order);
    remaining tools follow in their original order.

    Args:
        definitions: List of ToolDefinition objects (must have ``name``).
        order: Ordered list of tool names. Defaults to :data:`TOOL_ORDER`.

    Returns:
        A new list with the same elements, reordered.
    """
    if order is None:
        order = TOOL_ORDER

    rank: dict[str, int] = {name: idx for idx, name in enumerate(order)}
    sentinel = len(order)

    # Stable sort: tools in ``order`` come first (by rank), everything else
    # keeps its original relative order (all get the same ``sentinel`` key,
    # and Python's sort is stable).
    return sorted(
        definitions,
        key=lambda d: rank.get(getattr(d, "name", ""), sentinel),
    )
