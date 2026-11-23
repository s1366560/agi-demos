"""Guard the member directory and spreadsheet attachment at the package boundary."""

import csv
import json

import httpx
import pytest
from fastapi import HTTPException

from plugins.business.workspace.backend.workspace_directory_export import (
    _authorized_page,
    _check_csv,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2
from src.infrastructure.workspace_core.client import WorkspaceCoreProxyResponse

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("csv_text", "row_count", "width"),
    [
        ("a,b\n=42,0\n", 2, 2),
        ("a,b\n\tcell,0\n", 2, 2),
        ("a,b\nc,d\n", 1, 2),
        ("a,b\nc\n", 2, None),
        ('"unterminated\n', 1, 1),
        ("x" * 65536 + "\n", 1, None),
        ("truncated", 1, None),
    ],
)
def test_rejects_invalid_signed_csv_output(
    csv_text: str, row_count: int, width: int | None
) -> None:
    with pytest.raises((ValueError, csv.Error)):
        _check_csv(csv_text, row_count, width)


async def test_rejects_nonmatching_core_project_and_oversized_page() -> None:
    scope = ScopeBindingV2(tenant_id="t", project_id="p")
    row = {
        "id": "x",
        "name": "directory",
        "office_status": "active",
        "is_archived": False,
        "tenant_id": "t",
        "project_id": "another",
    }
    for payload, error in (
        (json.dumps([row]).encode(), ValueError),
        (b" " * (8 * 1024 * 1024 + 1), HTTPException),
    ):
        async with httpx.AsyncClient() as client:
            response = WorkspaceCoreProxyResponse(client, httpx.Response(200, content=payload))
            with pytest.raises(error):
                await _authorized_page(response, scope)
            await response.aclose()
