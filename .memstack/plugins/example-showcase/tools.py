"""Example tool implementations for the showcase plugin.

Each tool class follows the MemStack tool protocol:
  - name: str
  - description: str
  - get_parameters_schema() -> dict
  - validate_args(**kwargs) -> bool
  - async execute(**kwargs) -> str
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from typing import Any


class EchoTool:
    """Echo input text back, optionally uppercased.

    Demonstrates basic tool structure with parameter validation.
    """

    name = "showcase_echo"
    description = "Echo input text back. Optionally convert to uppercase."

    @staticmethod
    def get_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back",
                },
                "uppercase": {
                    "type": "boolean",
                    "description": "Convert to uppercase if true",
                    "default": False,
                },
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
        uppercase = kwargs.get("uppercase", False)
        result = text.upper() if uppercase else text
        return result


class RandomNumberTool:
    """Generate a random number within a range.

    Demonstrates numeric parameter validation and structured output.
    """

    name = "showcase_random"
    description = "Generate a random integer within a specified range."

    @staticmethod
    def get_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "min_value": {
                    "type": "integer",
                    "description": "Minimum value (inclusive)",
                    "default": 1,
                },
                "max_value": {
                    "type": "integer",
                    "description": "Maximum value (inclusive)",
                    "default": 100,
                },
            },
        }

    @staticmethod
    def validate_args(**kwargs: Any) -> bool:
        min_val = kwargs.get("min_value", 1)
        max_val = kwargs.get("max_value", 100)
        return isinstance(min_val, int) and isinstance(max_val, int) and min_val <= max_val

    async def execute(self, **kwargs: Any) -> str:
        min_val = kwargs.get("min_value", 1)
        max_val = kwargs.get("max_value", 100)
        if not isinstance(min_val, int) or not isinstance(max_val, int):
            raise ValueError("min_value and max_value must be integers")
        if min_val > max_val:
            raise ValueError("min_value must be <= max_value")
        result = random.randint(min_val, max_val)
        return json.dumps({"value": result, "range": [min_val, max_val]})


class TimestampTool:
    """Return the current UTC timestamp.

    Demonstrates a zero-parameter tool with structured JSON output.
    """

    name = "showcase_timestamp"
    description = "Return the current UTC timestamp in ISO 8601 format."

    @staticmethod
    def get_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    @staticmethod
    def validate_args(**kwargs: Any) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        now = datetime.now(UTC)
        return json.dumps(
            {
                "iso": now.isoformat(),
                "unix": int(now.timestamp()),
            }
        )
