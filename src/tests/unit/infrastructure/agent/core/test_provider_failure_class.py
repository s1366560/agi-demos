"""Provider balance failures stay labeled and do not select another provider."""

import pytest

from src.infrastructure.agent.core.llm_stream import classify_provider_failure

pytestmark = pytest.mark.unit


def test_balance_error_is_vendor_rate_limit_without_fallback() -> None:
    message, code = classify_provider_failure(
        RuntimeError("RateLimitError: Insufficient balance or no resource package")
    )
    assert code == "vendor_rate_limit"
    assert message.startswith("vendor_rate_limit:")
    assert "No alternate provider was selected" in message


def test_other_errors_keep_their_type_name() -> None:
    message, code = classify_provider_failure(ValueError("bad request"))
    assert code == "ValueError"
    assert message == "bad request"


def test_balance_rejection_is_not_retried() -> None:
    from src.infrastructure.agent.retry.policy import RetryPolicy

    policy = RetryPolicy()
    message, _code = classify_provider_failure(
        RuntimeError("RateLimitError: Insufficient balance or no resource package")
    )
    assert policy.is_retryable(RuntimeError(message)) is False
    assert policy.is_retryable(RuntimeError("Rate limit exceeded. Please wait")) is True
