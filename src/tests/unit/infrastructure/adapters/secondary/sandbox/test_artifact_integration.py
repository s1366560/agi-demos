"""Tests for sandbox artifact extraction helpers."""

import logging

import pytest

from src.infrastructure.adapters.secondary.sandbox.artifact_integration import (
    extract_artifacts_from_mcp_result,
    extract_artifacts_from_text,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.sandbox.artifact_integration"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_embedded_data_url_log_redacts_decoder_details(caplog):
    """Malformed embedded data URLs should be skipped without leaking decode details."""
    invalid_payload = "c2VjcmV0X3BheWxvYWQ"
    text = f"tool output data:image/png;base64,{invalid_payload}"

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        artifacts = await extract_artifacts_from_text(
            text=text,
            project_id="project-secret",
            tenant_id="tenant-secret",
            tool_execution_id="execution-secret",
        )

    assert artifacts == []
    assert "Failed to decode embedded data" in caplog.text
    assert invalid_payload not in caplog.text
    assert "Incorrect padding" not in caplog.text
    assert "error_type=Error" in caplog.text
    assert "has_mime_type=True" in caplog.text


@pytest.mark.unit
def test_invalid_mcp_image_log_redacts_tool_and_decoder_details(caplog):
    """Malformed MCP image content should not leak tool names or decoder details."""
    secret_tool_name = "secret-image-tool"
    invalid_payload = "c2VjcmV0X21jcF9pbWFnZQ"
    result = {
        "content": [
            {
                "type": "image",
                "data": invalid_payload,
                "mimeType": "image/png",
            }
        ]
    }

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        artifacts = extract_artifacts_from_mcp_result(result, secret_tool_name)

    assert artifacts == []
    assert "Failed to decode MCP image content" in caplog.text
    assert secret_tool_name not in caplog.text
    assert invalid_payload not in caplog.text
    assert "Incorrect padding" not in caplog.text
    assert "error_type=Error" in caplog.text
    assert "has_tool_name=True" in caplog.text
    assert "has_mime_type=True" in caplog.text


@pytest.mark.unit
def test_invalid_mcp_resource_log_redacts_uri_tool_and_decoder_details(caplog):
    """Malformed MCP resource blobs should not leak tool names, URIs, or decoder details."""
    secret_tool_name = "secret-resource-tool"
    secret_uri = "file:///workspace/secrets/result.png"
    invalid_blob = "c2VjcmV0X21jcF9yZXNvdXJjZQ"
    result = {
        "content": [
            {
                "type": "resource",
                "uri": secret_uri,
                "blob": invalid_blob,
                "mimeType": "image/png",
            }
        ]
    }

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        artifacts = extract_artifacts_from_mcp_result(result, secret_tool_name)

    assert artifacts == []
    assert "Failed to decode MCP resource blob" in caplog.text
    assert secret_tool_name not in caplog.text
    assert secret_uri not in caplog.text
    assert invalid_blob not in caplog.text
    assert "Incorrect padding" not in caplog.text
    assert "error_type=Error" in caplog.text
    assert "has_tool_name=True" in caplog.text
    assert "has_uri=True" in caplog.text
