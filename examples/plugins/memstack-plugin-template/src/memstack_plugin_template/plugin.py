"""Template plugin entry point for MemStack runtime discovery."""

from __future__ import annotations

from typing import Any, Dict


class TemplateEchoTool:
    """Minimal tool example exposed by template plugin."""

    name = "template_echo"
    description = "Echo input text from template plugin"

    @staticmethod
    def get_parameters_schema() -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back",
                }
            },
            "required": ["text"],
        }

    @staticmethod
    def validate_args(**kwargs: Any) -> bool:
        text = kwargs.get("text")
        return isinstance(text, str) and len(text) <= 10000

    async def execute(self, **kwargs: Any) -> str:
        text = kwargs.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return text


class TemplatePlugin:
    """Plugin class loaded by entry point group memstack.agent_plugins."""

    name = "template-plugin"

    def setup(self, api: Any) -> None:
        """Register plugin contributions into runtime API."""

        def _tool_factory(_context: Any) -> Dict[str, Any]:
            return {"template_echo": TemplateEchoTool()}

        api.register_tool_factory(_tool_factory)
