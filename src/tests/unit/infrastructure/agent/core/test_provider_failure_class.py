"""Provider balance failures stay labeled and do not select another provider."""

import pytest

from src.infrastructure.agent.core.llm_stream import classify_provider_failure

pytestmark = pytest.mark.unit


def test_balance_is_distinct_from_retryable_rate_limit() -> None:
    from src.infrastructure.agent.core.llm_stream import resolve_provider_after_failure
    from src.infrastructure.agent.retry.policy import RetryPolicy

    balance_message, balance_code, balance_class = classify_provider_failure(
        RuntimeError("RateLimitError: Insufficient balance or no resource package")
    )
    limit_message, limit_code, limit_class = classify_provider_failure(
        RuntimeError("Rate limit exceeded for this minute")
    )
    policy = RetryPolicy()
    assert balance_code == "vendor_balance"
    assert balance_class == "balance"
    assert policy.is_retryable(RuntimeError(balance_message)) is False
    assert limit_code == "vendor_rate_limit"
    assert limit_class == "rate_limit"
    assert policy.is_retryable(RuntimeError(limit_message)) is True
    assert (
        resolve_provider_after_failure(
            current_provider="zai",
            failure_class=balance_class,
            authorized_fallback=None,
        )
        == "zai"
    )
    assert (
        resolve_provider_after_failure(
            current_provider="zai",
            failure_class=balance_class,
            authorized_fallback="backup-provider",
        )
        == "zai"
    )


def test_other_errors_keep_their_type_name() -> None:
    message, code, failure_class = classify_provider_failure(ValueError("bad request"))
    assert code == "ValueError"
    assert failure_class == "other"
    assert message == "bad request"
