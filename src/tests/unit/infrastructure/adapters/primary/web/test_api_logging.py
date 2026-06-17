import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.middleware.api_logging import (
    install_api_access_log_middleware,
)


def _app() -> FastAPI:
    app = FastAPI()
    install_api_access_log_middleware(app)

    @app.get("/api/v1/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/api/v1/fail")
    async def fail() -> None:
        raise RuntimeError("boom")

    @app.get("/api/v1/shared/{share_token}")
    async def get_shared(share_token: str) -> dict[str, str]:
        return {"share_token": share_token}

    return app


def _api_log_payload(record: logging.LogRecord) -> dict[str, object]:
    _prefix, payload = record.getMessage().split(" ", 1)
    return dict(json.loads(payload))


@pytest.mark.unit
def test_api_access_log_uses_structured_single_line_format(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app())

    with caplog.at_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.api_access",
    ):
        response = client.get(
            "/api/v1/items/abc?token=secret",
            headers={"X-Request-ID": "request-123", "User-Agent": "test-client"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"

    [record] = [record for record in caplog.records if record.name.endswith(".api_access")]
    assert record.message.startswith("api_request ")
    payload = _api_log_payload(record)
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/items/abc"
    assert payload["route"] == "/api/v1/items/{item_id}"
    assert payload["status_code"] == 200
    assert payload["request_id"] == "request-123"
    assert payload["user_agent"] == "test-client"
    assert isinstance(payload["duration_ms"], float)
    assert "secret" not in record.message


@pytest.mark.unit
def test_api_access_log_emits_500_record_when_handler_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)

    with caplog.at_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.api_access",
    ):
        response = client.get("/api/v1/fail")

    assert response.status_code == 500
    [record] = [record for record in caplog.records if record.name.endswith(".api_access")]
    payload = _api_log_payload(record)
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/fail"
    assert payload["route"] == "/api/v1/fail"
    assert payload["status_code"] == 500
    assert isinstance(payload["request_id"], str)


@pytest.mark.unit
def test_api_access_log_redacts_shared_token_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app())

    with caplog.at_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.api_access",
    ):
        response = client.get("/api/v1/shared/secret-share-token")

    assert response.status_code == 200
    [record] = [record for record in caplog.records if record.name.endswith(".api_access")]
    payload = _api_log_payload(record)
    assert payload["path"] == "/api/v1/shared/{share_token}"
    assert payload["route"] == "/api/v1/shared/{share_token}"
    assert "secret-share-token" not in record.message
