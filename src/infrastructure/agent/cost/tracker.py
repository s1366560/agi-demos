"""Cost Tracker - Reference: OpenCode session/index.ts:412-463

Real-time cost tracking using Decimal for precise calculations.
Supports cache tokens, reasoning tokens, and context overflow pricing.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional


@dataclass
class TokenUsage:
    """Token usage breakdown."""

    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        """Total tokens used."""
        return self.input + self.output + self.reasoning

    @property
    def total_with_cache(self) -> int:
        """Total tokens including cache operations."""
        return self.total + self.cache_read + self.cache_write

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary."""
        return {
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "total": self.total,
        }


@dataclass
class CostResult:
    """Result of cost calculation."""

    cost: float
    tokens: TokenUsage

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cost": self.cost,
            "cost_formatted": f"${self.cost:.6f}",
            "tokens": self.tokens.to_dict(),
        }


@dataclass
class ModelCost:
    """Model cost configuration (per million tokens in USD)."""

    input: Decimal
    output: Decimal
    cache_read: Optional[Decimal] = None
    cache_write: Optional[Decimal] = None
    reasoning: Optional[Decimal] = None  # If different from output
    context_over_200k: Optional["ModelCost"] = None  # Pricing for >200k context


class BudgetExceededError(Exception):
    """Raised when a cost budget limit is exceeded."""

    def __init__(self, message: str, current_cost: float, limit: float):
        super().__init__(message)
        self.current_cost = current_cost
        self.limit = limit


class CostTracker:
    """
    Real-time cost tracker - Reference: OpenCode session/index.ts:412-463

    Features:
    - Decimal precision for accurate cost calculation
    - Support for cache tokens (Claude, Bedrock)
    - Support for reasoning tokens (o1, o3)
    - Context overflow pricing (>200k tokens)
    - Cumulative tracking across a session
    - Budget enforcement with per-request and per-session limits

    Example:
        tracker = CostTracker()

        result = tracker.calculate(
            usage={"input_tokens": 1000, "output_tokens": 500},
            model_name="claude-3-5-sonnet"
        )
        print(f"Cost: ${result.cost:.6f}")
        print(f"Total session cost: ${tracker.total_cost:.6f}")
    """

    # Model cost configurations (per million tokens in USD)
    # Updated as of January 2025
    MODEL_COSTS: Dict[str, ModelCost] = {
        # OpenAI models
        "gpt-4o": ModelCost(
            input=Decimal("2.50"),
            output=Decimal("10.00"),
        ),
        "gpt-4o-mini": ModelCost(
            input=Decimal("0.15"),
            output=Decimal("0.60"),
        ),
        "gpt-4-turbo": ModelCost(
            input=Decimal("10.00"),
            output=Decimal("30.00"),
        ),
        "gpt-4": ModelCost(
            input=Decimal("30.00"),
            output=Decimal("60.00"),
        ),
        "gpt-3.5-turbo": ModelCost(
            input=Decimal("0.50"),
            output=Decimal("1.50"),
        ),
        "o1": ModelCost(
            input=Decimal("15.00"),
            output=Decimal("60.00"),
            reasoning=Decimal("60.00"),
        ),
        "o1-mini": ModelCost(
            input=Decimal("3.00"),
            output=Decimal("12.00"),
            reasoning=Decimal("12.00"),
        ),
        "o3-mini": ModelCost(
            input=Decimal("1.10"),
            output=Decimal("4.40"),
            reasoning=Decimal("4.40"),
        ),
        # Anthropic models
        "claude-3-5-sonnet": ModelCost(
            input=Decimal("3.00"),
            output=Decimal("15.00"),
            cache_read=Decimal("0.30"),
            cache_write=Decimal("3.75"),
        ),
        "claude-3-5-haiku": ModelCost(
            input=Decimal("0.80"),
            output=Decimal("4.00"),
            cache_read=Decimal("0.08"),
            cache_write=Decimal("1.00"),
        ),
        "claude-3-opus": ModelCost(
            input=Decimal("15.00"),
            output=Decimal("75.00"),
            cache_read=Decimal("1.50"),
            cache_write=Decimal("18.75"),
        ),
        "claude-3-sonnet": ModelCost(
            input=Decimal("3.00"),
            output=Decimal("15.00"),
            cache_read=Decimal("0.30"),
            cache_write=Decimal("3.75"),
        ),
        "claude-3-haiku": ModelCost(
            input=Decimal("0.25"),
            output=Decimal("1.25"),
            cache_read=Decimal("0.03"),
            cache_write=Decimal("0.30"),
        ),
        # Google models
        "gemini-2.0-flash": ModelCost(
            input=Decimal("0.10"),
            output=Decimal("0.40"),
        ),
        "gemini-1.5-pro": ModelCost(
            input=Decimal("1.25"),
            output=Decimal("5.00"),
        ),
        "gemini-1.5-flash": ModelCost(
            input=Decimal("0.075"),
            output=Decimal("0.30"),
        ),
        "gemini-1.0-pro": ModelCost(
            input=Decimal("0.50"),
            output=Decimal("1.50"),
        ),
        # Alibaba Qwen models
        "qwen-turbo": ModelCost(
            input=Decimal("0.30"),
            output=Decimal("0.60"),
        ),
        "qwen-plus": ModelCost(
            input=Decimal("0.80"),
            output=Decimal("2.00"),
        ),
        "qwen-max": ModelCost(
            input=Decimal("2.40"),
            output=Decimal("9.60"),
        ),
        "qwen-long": ModelCost(
            input=Decimal("0.14"),
            output=Decimal("0.28"),
        ),
        # DeepSeek models
        "deepseek-chat": ModelCost(
            input=Decimal("0.14"),
            output=Decimal("0.28"),
            cache_read=Decimal("0.014"),
        ),
        "deepseek-coder": ModelCost(
            input=Decimal("0.14"),
            output=Decimal("0.28"),
            cache_read=Decimal("0.014"),
        ),
        "deepseek-reasoner": ModelCost(
            input=Decimal("0.55"),
            output=Decimal("2.19"),
            reasoning=Decimal("2.19"),
            cache_read=Decimal("0.14"),
        ),
        # Mistral models
        "mistral-large": ModelCost(
            input=Decimal("2.00"),
            output=Decimal("6.00"),
        ),
        "mistral-medium": ModelCost(
            input=Decimal("2.70"),
            output=Decimal("8.10"),
        ),
        "mistral-small": ModelCost(
            input=Decimal("0.20"),
            output=Decimal("0.60"),
        ),
        "codestral": ModelCost(
            input=Decimal("0.20"),
            output=Decimal("0.60"),
        ),
        # ZhipuAI models
        "glm-4": ModelCost(
            input=Decimal("1.40"),
            output=Decimal("1.40"),
        ),
        "glm-4-flash": ModelCost(
            input=Decimal("0.01"),
            output=Decimal("0.01"),
        ),
    }

    # Default cost for unknown models
    DEFAULT_COST = ModelCost(
        input=Decimal("0.15"),
        output=Decimal("0.60"),
    )

    def __init__(
        self,
        context_limit: int = 200000,
        max_cost_per_request: float = 0,
        max_cost_per_session: float = 0,
    ):
        """
        Initialize cost tracker.

        Args:
            context_limit: Context size threshold for overflow pricing (default: 200k)
            max_cost_per_request: Maximum cost per single LLM call (0 = unlimited)
            max_cost_per_session: Maximum cumulative cost per session (0 = unlimited)
        """
        self.context_limit = context_limit
        self.max_cost_per_request = Decimal(str(max_cost_per_request))
        self.max_cost_per_session = Decimal(str(max_cost_per_session))
        self.total_cost = Decimal("0")
        self.total_tokens = TokenUsage()
        self.call_count = 0

    def calculate(
        self,
        usage: Dict[str, Any],
        model_name: str,
        provider_metadata: Optional[Dict[str, Any]] = None,
    ) -> CostResult:
        """
        Calculate cost for a single LLM call.

        Reference: OpenCode getUsage()

        Args:
            usage: Token usage dict from LLM response
            model_name: Name of the model used
            provider_metadata: Optional provider-specific metadata

        Returns:
            CostResult with cost and token breakdown
        """
        # Get model cost configuration
        cost_info = self._get_cost_info(model_name)

        # Parse token usage with provider-specific handling
        tokens = self._parse_usage(usage, provider_metadata)

        # Check for context overflow pricing
        if cost_info.context_over_200k and (tokens.input + tokens.cache_read) > self.context_limit:
            cost_info = cost_info.context_over_200k

        # Calculate cost using Decimal for precision
        cost = self._calculate_cost(tokens, cost_info)

        # Update cumulative totals
        self._update_totals(cost, tokens)

        return CostResult(cost=float(cost), tokens=tokens)

    def _parse_usage(
        self,
        usage: Dict[str, Any],
        provider_metadata: Optional[Dict[str, Any]] = None,
    ) -> TokenUsage:
        """
        Parse token usage from LLM response.

        Handles provider-specific formats:
        - Anthropic: cacheCreationInputTokens, cacheReadInputTokens
        - Bedrock: usage.cacheWriteInputTokens, usage.cacheReadInputTokens
        - OpenAI: prompt_tokens, completion_tokens
        - Standard: input_tokens, output_tokens

        Args:
            usage: Raw usage dict from LLM
            provider_metadata: Provider-specific metadata

        Returns:
            Normalized TokenUsage object
        """
        # Standard fields
        input_tokens = self._safe_int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = self._safe_int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0
        )
        reasoning_tokens = self._safe_int(usage.get("reasoning_tokens") or 0)

        # Cache tokens - check provider metadata
        cache_read = 0
        cache_write = 0

        # Direct cache fields
        cache_read = self._safe_int(
            usage.get("cache_read_tokens") or usage.get("cached_tokens") or 0
        )
        cache_write = self._safe_int(
            usage.get("cache_write_tokens") or usage.get("cache_creation_tokens") or 0
        )

        # Anthropic-specific (in provider metadata)
        if provider_metadata:
            anthropic = provider_metadata.get("anthropic", {})
            if anthropic:
                cache_write = self._safe_int(
                    anthropic.get("cacheCreationInputTokens") or cache_write
                )
                # Anthropic's cachedInputTokens is already in usage.cachedInputTokens

            # Bedrock-specific
            bedrock = provider_metadata.get("bedrock", {})
            if bedrock:
                bedrock_usage = bedrock.get("usage", {})
                cache_write = self._safe_int(
                    bedrock_usage.get("cacheWriteInputTokens") or cache_write
                )
                cache_read = self._safe_int(bedrock_usage.get("cacheReadInputTokens") or cache_read)

        # Handle Anthropic's excluded cached tokens
        # If cached tokens are not included in input_tokens, add them
        cached_input = self._safe_int(
            usage.get("cachedInputTokens") or usage.get("cached_input_tokens") or 0
        )
        if cached_input > 0 and cache_read == 0:
            cache_read = cached_input

        return TokenUsage(
            input=input_tokens,
            output=output_tokens,
            reasoning=reasoning_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
        )

    def _calculate_cost(self, tokens: TokenUsage, cost_info: ModelCost) -> Decimal:
        """
        Calculate cost using Decimal precision.

        Args:
            tokens: Token usage breakdown
            cost_info: Model cost configuration

        Returns:
            Cost in USD as Decimal
        """
        million = Decimal("1000000")

        cost = Decimal("0")

        # Input tokens
        cost += Decimal(tokens.input) * cost_info.input / million

        # Output tokens
        cost += Decimal(tokens.output) * cost_info.output / million

        # Reasoning tokens (use reasoning rate if available, else output rate)
        if tokens.reasoning > 0:
            reasoning_rate = cost_info.reasoning or cost_info.output
            cost += Decimal(tokens.reasoning) * reasoning_rate / million

        # Cache read tokens
        if tokens.cache_read > 0 and cost_info.cache_read:
            cost += Decimal(tokens.cache_read) * cost_info.cache_read / million

        # Cache write tokens
        if tokens.cache_write > 0 and cost_info.cache_write:
            cost += Decimal(tokens.cache_write) * cost_info.cache_write / million

        return cost

    def _update_totals(self, cost: Decimal, tokens: TokenUsage) -> None:
        """Update cumulative totals and enforce budget limits."""
        # Enforce per-request limit
        if self.max_cost_per_request > 0 and cost > self.max_cost_per_request:
            raise BudgetExceededError(
                f"Request cost ${float(cost):.6f} exceeds per-request limit "
                f"${float(self.max_cost_per_request):.6f}",
                current_cost=float(cost),
                limit=float(self.max_cost_per_request),
            )

        self.total_cost += cost

        # Enforce per-session limit
        if self.max_cost_per_session > 0 and self.total_cost > self.max_cost_per_session:
            raise BudgetExceededError(
                f"Session cost ${float(self.total_cost):.6f} exceeds session limit "
                f"${float(self.max_cost_per_session):.6f}",
                current_cost=float(self.total_cost),
                limit=float(self.max_cost_per_session),
            )

        self.total_tokens.input += tokens.input
        self.total_tokens.output += tokens.output
        self.total_tokens.reasoning += tokens.reasoning
        self.total_tokens.cache_read += tokens.cache_read
        self.total_tokens.cache_write += tokens.cache_write
        self.call_count += 1

    def _get_cost_info(self, model_name: str) -> ModelCost:
        """
        Get model cost configuration by name.

        Uses fuzzy matching to find the best match.

        Args:
            model_name: Name of the model (case insensitive)

        Returns:
            ModelCost configuration
        """
        model_lower = model_name.lower()

        # Exact match first
        if model_lower in self.MODEL_COSTS:
            return self.MODEL_COSTS[model_lower]

        # Fuzzy match - find model key that's contained in the model name
        for key, cost in self.MODEL_COSTS.items():
            if key in model_lower:
                return cost

        # Check for common prefixes
        for key, cost in self.MODEL_COSTS.items():
            if model_lower.startswith(key.split("-")[0]):
                return cost

        return self.DEFAULT_COST

    def needs_compaction(self, tokens: TokenUsage) -> bool:
        """
        Check if context compaction is needed.

        Args:
            tokens: Current token usage

        Returns:
            True if total context exceeds 80% of limit
        """
        total_context = tokens.input + tokens.cache_read
        return total_context > self.context_limit * 0.8

    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get summary of session costs and tokens.

        Returns:
            Summary dict with totals and averages
        """
        avg_cost = float(self.total_cost / self.call_count) if self.call_count > 0 else 0

        return {
            "total_cost": float(self.total_cost),
            "total_cost_formatted": f"${float(self.total_cost):.6f}",
            "call_count": self.call_count,
            "average_cost_per_call": avg_cost,
            "total_tokens": self.total_tokens.to_dict(),
        }

    def reset(self) -> None:
        """Reset counters for a new session (budget limits are preserved)."""
        self.total_cost = Decimal("0")
        self.total_tokens = TokenUsage()
        self.call_count = 0

    @staticmethod
    def _safe_int(value: Any) -> int:  # noqa: ANN401
        """
        Safely convert a value to int.

        Args:
            value: Value to convert

        Returns:
            Integer value, or 0 if conversion fails
        """
        if value is None:
            return 0
        try:
            result = int(value)
            return result if result >= 0 else 0
        except (ValueError, TypeError):
            return 0
