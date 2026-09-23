import logging

from src.infrastructure.logging_redaction import (
    redact_sensitive_log_record,
    redact_sensitive_log_text,
)


def test_redacts_sensitive_url_query_values() -> None:
    text = (
        "connected to wss://msg-frontier.example/ws?"
        "fpid=493&access_key=abc123&service_id=33554678&ticket=ticket-secret"
    )

    redacted = redact_sensitive_log_text(text)

    assert "abc123" not in redacted
    assert "ticket-secret" not in redacted
    assert "access_key=<redacted>" in redacted
    assert "ticket=<redacted>" in redacted
    assert "service_id=33554678" in redacted


def test_redacts_formatted_log_record_args() -> None:
    record = logging.LogRecord(
        "Lark",
        logging.INFO,
        __file__,
        1,
        "connected to %s with %s",
        (
            "wss://example/ws?ticket=secret-ticket",
            "Bearer live-token-value",
        ),
        None,
    )

    redact_sensitive_log_record(record)

    message = record.getMessage()
    assert "secret-ticket" not in message
    assert "live-token-value" not in message
    assert "ticket=<redacted>" in message
    assert "Bearer <redacted>" in message


def test_redacts_memstack_api_keys() -> None:
    key = "ms_sk_" + ("a" * 64)

    redacted = redact_sensitive_log_text(f"Authorization failed for {key}")

    assert key not in redacted
    assert "<redacted>" in redacted


def test_redacts_oauth_callback_in_uvicorn_access_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1234",
            "GET",
            "/api/v1/plugin-marketplace/v3/oauth/callback"
            "?code=authorization-secret&state=challenge-secret&result=ok",
            "1.1",
            200,
        ),
        None,
    )

    message = redact_sensitive_log_record(record).getMessage()

    assert "authorization-secret" not in message
    assert "challenge-secret" not in message
    assert "code=<redacted>&state=<redacted>&result=ok" in message
    assert 'HTTP/1.1" 200' in message


def test_redacts_pkce_verifier_query() -> None:
    assert redact_sensitive_log_text("/token?code_verifier=private-verifier") == (
        "/token?code_verifier=<redacted>"
    )
