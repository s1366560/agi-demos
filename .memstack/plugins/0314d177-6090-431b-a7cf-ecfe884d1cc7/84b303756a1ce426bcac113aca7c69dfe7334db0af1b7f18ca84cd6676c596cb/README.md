# Marketplace Demo

An executable example with no API key or external service dependency. Requires Python 3.

The plugin contributes a skill, an MCP echo tool, an HTML MCP app resource, and
MemStack lifecycle hooks. All scripts are packaged inside the immutable snapshot.
Hooks read JSON from standard input and write a result to standard output.

The `.codex-plugin/plugin.json` manifest uses Codex-style Skills/MCP/Apps entries.
The companion `hooks/hooks.json` and `mcp_server` app mapping are documented
MemStack extensions, not a claim of compatibility with private Codex connectors.
