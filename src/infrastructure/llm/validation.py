"""
Structured output validation and retry logic.

Provides automatic retry with schema validation for LLM responses
that need to conform to specific JSON structures.

Features:
- Pydantic model validation
- Automatic retry with error feedback
- Progressive prompt refinement
- Support for partial responses

Example:
    validator = StructuredOutputValidator(max_retries=3)

    response = await validator.generate_validated(
        llm_client=client,
        messages=messages,
        response_model=MyModel,
    )
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.domain.llm_providers.llm_types import LLMClient, Message, ModelSize

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class ValidationConfig:
    """Configuration for structured output validation."""

    # Maximum number of retry attempts
    max_retries: int = 3

    # Whether to include validation errors in retry prompts
    include_error_feedback: bool = True

    # Whether to include schema in system prompt
    include_schema_in_prompt: bool = True

    # Temperature for retry attempts (lower = more deterministic)
    retry_temperature: float = 0.0

    # Maximum tokens for response
    max_tokens: int = 4096


@dataclass
class ValidationResult:
    """Result of a validation attempt."""

    success: bool
    data: dict[str, Any] | None = None
    model_instance: BaseModel | None = None
    raw_response: str | None = None
    error: str | None = None
    attempts: int = 0


def _strip_code_blocks(content: str) -> str:
    """Strip markdown code block markers from content."""
    content = content.strip()

    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def _find_json_boundaries(content: str) -> str:
    """Find and extract JSON object or array from content with surrounding text."""
    # Skip to first JSON start character if needed
    if not (content.startswith("{") or content.startswith("[")):
        json_start = -1
        for i, char in enumerate(content):
            if char in "{[":
                json_start = i
                break

        if json_start >= 0:
            content = content[json_start:]

    # Find matching end bracket
    open_char, close_char = _get_bracket_pair(content)
    if open_char is not None and close_char is not None:
        content = _find_matching_bracket(content, open_char, close_char)

    return content


def _get_bracket_pair(content: str) -> tuple[str | None, str | None]:
    """Return the bracket pair for the content's opening character."""
    if content.startswith("{"):
        return "{", "}"
    if content.startswith("["):
        return "[", "]"
    return None, None


def _find_matching_bracket(content: str, open_char: str, close_char: str) -> str:
    """Find the matching closing bracket and return the substring."""
    depth = 0
    for i, char in enumerate(content):
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return content[: i + 1]
    return content


def _inject_schema_into_messages(
    working_messages: list[Message | dict[str, Any]],
    schema_prompt: str,
) -> list[Message | dict[str, Any]]:
    """Inject schema prompt into the system message of the message list.

    If a system message exists, appends the schema prompt to it.
    Otherwise, inserts a new system message at the beginning.

    Returns:
        A new message list with the schema injected.
    """
    result = list(working_messages)

    for i, msg in enumerate(result):
        role = msg.get("role") if isinstance(msg, dict) else msg.role
        if role == "system":
            content = msg.get("content") if isinstance(msg, dict) else msg.content
            if isinstance(msg, dict):
                result[i] = {"role": "system", "content": (content or "") + schema_prompt}
            else:
                result[i] = Message(role="system", content=(content or "") + schema_prompt)
            return result

    # No system message found -- insert one
    result.insert(
        0,
        {"role": "system", "content": f"You are a helpful assistant.{schema_prompt}"},
    )
    return result


class StructuredOutputValidator:
    """
    Validator for structured LLM outputs with automatic retry.

    Handles JSON parsing, Pydantic validation, and retry logic
    with error feedback for improved success rates.
    """

    def __init__(self, config: ValidationConfig | None = None) -> None:
        """
        Initialize the validator.

        Args:
            config: Validation configuration
        """
        self.config = config or ValidationConfig()

    def _extract_json(self, content: str) -> str:
        """
        Extract JSON from response content.

        Handles various formats:
        - Raw JSON
        - JSON in code blocks
        - JSON with surrounding text

        Args:
            content: Raw response content

        Returns:
            Extracted JSON string
        """
        content = _strip_code_blocks(content)
        return _find_json_boundaries(content)

    def _build_schema_prompt(self, response_model: type[BaseModel]) -> str:
        """
        Build a prompt section describing the expected schema.

        Args:
            response_model: Pydantic model class

        Returns:
            Schema description string
        """
        schema = response_model.model_json_schema()

        # Simplify schema for prompt
        simplified = {
            "type": schema.get("type", "object"),
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }

        return (
            "\n\nYou MUST respond with a valid JSON object matching this schema:\n"
            f"```json\n{json.dumps(simplified, indent=2)}\n```\n"
            "Do not include any text before or after the JSON."
        )

    def _build_retry_prompt(
        self,
        original_response: str,
        error: str,
        response_model: type[BaseModel],
    ) -> str:
        """
        Build a retry prompt with error feedback.

        Args:
            original_response: The failed response
            error: Validation error message
            response_model: Expected model

        Returns:
            Retry prompt
        """
        schema_prompt = self._build_schema_prompt(response_model)

        return (
            f"Your previous response was invalid:\n"
            f"```\n{original_response[:500]}{'...' if len(original_response) > 500 else ''}\n```\n\n"
            f"Error: {error}\n\n"
            f"Please provide a corrected response.{schema_prompt}"
        )

    def validate(
        self,
        content: str,
        response_model: type[T],
    ) -> ValidationResult:
        """
        Validate a response against a Pydantic model.

        Args:
            content: Raw response content
            response_model: Expected Pydantic model

        Returns:
            ValidationResult with success status and data
        """
        try:
            # Extract JSON
            json_str = self._extract_json(content)

            # Parse JSON
            data = json.loads(json_str)

            # Validate with Pydantic
            instance = response_model.model_validate(data)

            return ValidationResult(
                success=True,
                data=instance.model_dump(),
                model_instance=instance,
                raw_response=content,
            )

        except json.JSONDecodeError as e:
            return ValidationResult(
                success=False,
                raw_response=content,
                error=f"JSON parsing error: {e}",
            )

        except ValidationError as e:
            # Format validation errors nicely
            error_messages = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                error_messages.append(f"{loc}: {err['msg']}")

            return ValidationResult(
                success=False,
                raw_response=content,
                error=f"Validation errors: {'; '.join(error_messages)}",
            )

        except Exception as e:
            return ValidationResult(
                success=False,
                raw_response=content,
                error=f"Unexpected error: {e}",
            )

    async def generate_validated(
        self,
        llm_client: LLMClient,
        messages: list[Message] | list[dict[str, Any]],
        response_model: type[T],
        **kwargs: Any,
    ) -> ValidationResult:
        """
        Generate a response and validate it, with automatic retry.

        Args:
            llm_client: LLM client to use
            messages: Input messages
            response_model: Expected Pydantic model
            **kwargs: Additional arguments for LLM

        Returns:
            ValidationResult with validated data or error
        """
        # Prepare messages
        working_messages: list[Message | dict[str, Any]] = list(messages)

        # Add schema to system prompt if configured
        if self.config.include_schema_in_prompt:
            schema_prompt = self._build_schema_prompt(response_model)
            working_messages = _inject_schema_into_messages(working_messages, schema_prompt)

        return await self._retry_loop(llm_client, working_messages, response_model, **kwargs)

    async def _retry_loop(
        self,
        llm_client: LLMClient,
        working_messages: list[Message | dict[str, Any]],
        response_model: type[T],
        **kwargs: Any,
    ) -> ValidationResult:
        """Execute the generate-validate-retry loop.

        Returns:
            ValidationResult after retries are exhausted or success.
        """
        last_result: ValidationResult | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await self._attempt_generation(
                    llm_client,
                    working_messages,
                    response_model,
                    attempt,
                    **kwargs,
                )

                if result.success:
                    if attempt > 0:
                        logger.info(
                            f"Structured output validation succeeded after {attempt + 1} attempts"
                        )
                    return result

                last_result = result

                # Prepare retry if we have more attempts
                if attempt < self.config.max_retries and self.config.include_error_feedback:
                    retry_prompt = self._build_retry_prompt(
                        result.raw_response or "", result.error or "Unknown error", response_model
                    )
                    working_messages.append(
                        {"role": "assistant", "content": result.raw_response or ""}
                    )
                    working_messages.append({"role": "user", "content": retry_prompt})

                    logger.debug(
                        f"Validation failed (attempt {attempt + 1}), retrying: {result.error}"
                    )

            except Exception as e:
                logger.error(f"Error during validated generation (attempt {attempt + 1}): {e}")
                last_result = ValidationResult(
                    success=False,
                    error=str(e),
                    attempts=attempt + 1,
                )

        # Return last result after all retries exhausted
        if last_result:
            logger.warning(
                f"Structured output validation failed after {last_result.attempts} attempts: "
                f"{last_result.error}"
            )
            return last_result

        return ValidationResult(
            success=False,
            error="No response generated",
            attempts=self.config.max_retries + 1,
        )

    async def _attempt_generation(
        self,
        llm_client: LLMClient,
        working_messages: list[Message | dict[str, Any]],
        response_model: type[T],
        attempt: int,
        **kwargs: Any,
    ) -> ValidationResult:
        """Execute a single generation + validation attempt."""
        temperature = (
            self.config.retry_temperature if attempt > 0 else kwargs.get("temperature", 0.0)
        )

        response = await llm_client.generate_response(
            messages=[m for m in working_messages if isinstance(m, Message)],
            max_tokens=self.config.max_tokens,
            model_size=ModelSize.medium,
        )

        content = response.get("content", "")
        if not content:
            return ValidationResult(
                success=False,
                raw_response=str(response),
                error="Empty response from LLM",
                attempts=attempt + 1,
            )

        result = self.validate(content, response_model)
        result.attempts = attempt + 1
        return result


# Global validator instance
_validator: StructuredOutputValidator | None = None


def get_structured_validator() -> StructuredOutputValidator:
    """Get the global structured output validator."""
    global _validator
    if _validator is None:
        _validator = StructuredOutputValidator()
    return _validator
