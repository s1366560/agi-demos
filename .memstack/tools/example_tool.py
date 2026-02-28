"""Example custom tool -- copy and adapt for your own tools.

Drop any ``.py`` file into ``.memstack/tools/`` and it will be auto-
discovered at agent startup.  The only requirement is that each tool
function is decorated with ``@tool_define``.

Lifecycle
---------
1. ``CustomToolLoader`` scans ``.memstack/tools/*.py`` and
   ``.memstack/tools/<name>/tool.py`` (package-style).
2. Each file is dynamically imported; ``@tool_define`` registers the
   tool into a temporary snapshot of the global registry.
3. If a ``ToolHookRegistry`` is provided, definition hooks run on each
   ``ToolInfo`` (they may modify metadata or suppress the tool).
4. Successfully loaded tools are merged into the agent's tool set.

Minimal skeleton
----------------
::

    from memstack_tools import tool_define, ToolResult

    @tool_define(
        name="my_tool",
        description="One-line description shown to the LLM.",
        parameters={
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "..."},
            },
            "required": ["arg1"],
        },
        permission="read",       # "read" | "write" | "admin"
        category="custom",
    )
    async def my_tool(ctx, arg1: str) -> ToolResult:
        return ToolResult(output=f"Got {arg1}")

Notes
-----
* ``ctx`` is a :class:`ToolContext` instance giving access to the
  current conversation, project, and tenant ids.
* Return a :class:`ToolResult` with ``output`` (str) shown to the LLM
  and an optional ``error`` field.
* Errors during import are isolated -- they will NOT break other tools.
* The ``permission`` field controls the agent's ability to call the
  tool without explicit user approval (``"read"`` is the safest).
"""

from memstack_tools import ToolResult, tool_define


@tool_define(
    name="example_echo",
    description=(
        "Echo back the provided message.  This is a demonstration "
        "tool -- feel free to delete or replace it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to echo back.",
            },
        },
        "required": ["message"],
    },
    permission="read",
    category="custom",
)
async def example_echo(ctx: object, message: str) -> ToolResult:
    """Return *message* unchanged so the agent can see it."""
    return ToolResult(output=message)
