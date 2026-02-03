"""
LLM Classifier for Plan Mode triggering.

This module provides the LLMClassifier class which uses an LLM
to classify whether a query should trigger Plan Mode.

This is Layer 3 of the Hybrid Detection Strategy, used for
queries with ambiguous heuristic scores (0.2 to 0.8).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ClassificationError(Exception):
    """
    Raised when LLM classification fails.

    Attributes:
        message: Error message
        cause: Optional underlying exception
    """

    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        self.cause = cause
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


@dataclass(frozen=True)
class ClassificationResult:
    """
    Result of LLM-based classification.

    Attributes:
        should_trigger: Whether Plan Mode should be triggered
        confidence: Confidence score (0.0 to 1.0)
        reasoning: Explanation for the classification
    """

    should_trigger: bool
    confidence: float
    reasoning: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "should_trigger": self.should_trigger,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


class LLMClassifier:
    """
    LLM-based classifier for Plan Mode triggering.

    Uses an LLM to determine if a query requires Plan Mode.
    This is Layer 3 of the Hybrid Detection Strategy.

    The LLM is prompted to return structured JSON output:
    {
        "should_trigger": true/false,
        "confidence": 0.0-1.0,
        "reasoning": "explanation"
    }

    Attributes:
        llm_client: LLM client with async complete() method
        confidence_threshold: Minimum confidence for classification (default: 0.7)
    """

    # System prompt for classification
    SYSTEM_PROMPT = """You are a Plan Mode classifier for an AI agent.

Your task is to determine if a user query requires Plan Mode.

Plan Mode should be triggered when:
- The query involves multi-step implementation work
- The query requires planning before execution
- The user is asking to build/create/develop something complex
- The query involves multiple files or components
- The query has dependencies or requires sequencing

Plan Mode should NOT be triggered when:
- The query is a simple question
- The query is a one-liner command
- The query is conversational or informational
- The query can be answered directly without planning

Return your response as JSON with this exact format:
{
    "should_trigger": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}

Be conservative - if uncertain, prefer should_trigger=false."""

    def __init__(
        self,
        llm_client: Any,
        confidence_threshold: float = 0.7,
    ) -> None:
        """
        Initialize the LLMClassifier.

        Args:
            llm_client: LLM client with async complete(prompt) -> str method
            confidence_threshold: Minimum confidence (default: 0.7)

        Raises:
            ValueError: If confidence_threshold is not in [0, 1]
        """
        if not 0 <= confidence_threshold <= 1:
            raise ValueError(
                f"confidence_threshold must be in [0, 1], got {confidence_threshold}"
            )

        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold

        # Pre-compile JSON extraction regex
        self._json_pattern = re.compile(r"\{.*\}", re.DOTALL)

    async def classify(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> ClassificationResult:
        """
        Classify whether the query should trigger Plan Mode.

        Args:
            query: The user query to classify
            conversation_context: Optional conversation history for context

        Returns:
            ClassificationResult with should_trigger, confidence, and reasoning

        Raises:
            ClassificationError: If classification fails
        """
        if not query or not query.strip():
            raise ClassificationError("Query cannot be empty")

        try:
            # Build the prompt
            prompt = self._build_prompt(query, conversation_context)

            # Call LLM
            response = await self._call_llm(prompt)

            # Parse the response
            parsed = self._parse_response(response)

            # Validate and clamp fields
            should_trigger = bool(parsed.get("should_trigger", False))
            raw_confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, raw_confidence))
            reasoning = str(parsed.get("reasoning", ""))

            return ClassificationResult(
                should_trigger=should_trigger,
                confidence=confidence,
                reasoning=reasoning,
            )

        except ClassificationError:
            raise
        except Exception as e:
            raise ClassificationError(
                f"LLM classification failed: {e}",
                cause=e,
            )

    def _build_prompt(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Build the classification prompt.

        Args:
            query: The user query
            conversation_context: Optional conversation history

        Returns:
            Complete prompt string
        """
        prompt_parts = [self.SYSTEM_PROMPT]

        # Add conversation context if available
        if conversation_context:
            context_str = self._format_conversation_context(conversation_context)
            prompt_parts.append("\nConversation History:")
            prompt_parts.append(context_str)

        # Add the current query
        prompt_parts.append("\nCurrent Query:")
        prompt_parts.append(query)

        # Add format reminder
        prompt_parts.append("\nRemember: Return only JSON, no other text.")

        return "\n".join(prompt_parts)

    def _format_conversation_context(
        self,
        context: List[Dict[str, str]],
    ) -> str:
        """
        Format conversation context for the prompt.

        Args:
            context: List of message dicts with 'role' and 'content'

        Returns:
            Formatted context string
        """
        formatted = []
        for msg in context[-5:]:  # Last 5 messages for context
            role = msg.get("role", "user")
            content = msg.get("content", "")
            formatted.append(f"{role}: {content}")

        return "\n".join(formatted)

    async def _call_llm(self, prompt: str) -> str:
        """
        Call the LLM with the prompt.

        Args:
            prompt: The prompt to send

        Returns:
            LLM response text

        Raises:
            Exception: If LLM call fails
        """
        # Try different async methods
        if hasattr(self.llm_client, "complete"):
            result = self.llm_client.complete(prompt)
            # Handle both coroutine and direct async call
            if hasattr(result, "__await__"):
                response = await result
            else:
                response = result
        elif hasattr(self.llm_client, "generate"):
            result = self.llm_client.generate(prompt)
            if hasattr(result, "__await__"):
                response = await result
            else:
                response = result
        elif hasattr(self.llm_client, "achat"):
            result = self.llm_client.achat(prompt)
            if hasattr(result, "__await__"):
                response = await result
            else:
                response = result
        else:
            raise RuntimeError(
                "LLM client has no compatible async method"
            )

        return response

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse the LLM JSON response.

        Args:
            response: Raw LLM response string

        Returns:
            Parsed dictionary

        Raises:
            ClassificationError: If parsing fails
        """
        response = response.strip()

        # Try extracting JSON from markdown code blocks
        if "```" in response:
            # Extract content from code block
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if match:
                response = match.group(1)

        # Try to find JSON object in response
        json_match = self._json_pattern.search(response)
        if json_match:
            response = json_match.group(0)

        # Parse JSON
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            raise ClassificationError(
                f"Failed to parse LLM response as JSON: {e}",
                cause=e,
            )

        # Validate required fields
        required_fields = ["should_trigger", "confidence", "reasoning"]
        missing_fields = [
            field for field in required_fields if field not in parsed
        ]

        if missing_fields:
            raise ClassificationError(
                f"Missing required fields in LLM response: {missing_fields}"
            )

        return parsed
