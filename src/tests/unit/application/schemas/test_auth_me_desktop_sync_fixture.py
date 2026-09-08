"""Keep the native sync HTTP fixture aligned with auth/me's production response schema."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.application.schemas.auth import User


@pytest.mark.unit
def test_native_sync_auth_fixture_matches_production_user_serialization() -> None:
    root = Path(__file__).resolve().parents[5]
    fixture = (
        root
        / "agi-stack/apps/desktop/sidecar/src/local_runtime/knowledge_authority_v2"
        / "auth_me_fixture.json"
    )
    user = User(
        user_id="remote-actor",
        email="sync@example.com",
        name="Sync contract fixture",
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    payload = user.model_dump(mode="json", by_alias=True)
    assert payload == json.loads(fixture.read_text())
    assert payload["user_id"] == "remote-actor"
    assert payload["is_active"] is True
    assert "id" not in payload
