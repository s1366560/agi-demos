"""Native discovery consumes production catalog schemas and rejects authority injection."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from src.application.schemas.project import ProjectListResponse, ProjectResponse
from src.application.schemas.tenant import TenantListResponse, TenantResponse

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = ROOT / "shared/schemas/knowledge"
SCHEMA = json.loads((SCHEMAS / "native-knowledge.v1.schema.json").read_text())
REGISTRY = Registry().with_resources(
    (document["$id"], Resource.from_contents(document))
    for path in SCHEMAS.glob("*.json")
    for document in [json.loads(path.read_text())]
)
SCOPE = {
    "tenant_id": "local-tenant",
    "project_id": "local-project",
    "context_revision": 1,
    "profile_id": "native-fixture",
    "generation": 1,
    "digest": "ab" * 32,
}
TARGET = {
    "scope": SCOPE,
    "expected_connection_revision": "cd" * 32,
    "tenant_id": "remote-tenant",
    "project_id": "remote-project",
    "expected_generation": {
        "contract_version": "1.0.0",
        "descriptor": {"profile_id": "cloud-fixture", "generation": 81, "digest": "ef" * 32},
    },
}


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": SCHEMA["$id"] + "#/$defs/NativeKnowledge" + name}, registry=REGISTRY
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("SyncConnectionRequest", {"scope"}),
        ("SyncTenantsRequest", {"scope", "expected_connection_revision"}),
        ("SyncProjectsRequest", {"scope", "expected_connection_revision", "tenant_id"}),
        (
            "SyncEnrollmentRequest",
            {"scope", "expected_connection_revision", "tenant_id", "project_id"},
        ),
        ("SyncTargetRequest", set(TARGET)),
    ],
)
def test_sync_connection_requests_share_strict_native_schema(name: str, fields: set[str]) -> None:
    request = {field: TARGET[field] for field in fields}
    validator(name).validate(request)
    for field in ("credential", "base_url", "authority", "actor_id", "remote_actor_id"):
        assert not validator(name).is_valid({**request, field: "forged"})
    for field in fields:
        missing = {key: value for key, value in request.items() if key != field}
        assert not validator(name).is_valid(missing)


@pytest.mark.unit
@pytest.mark.parametrize("generation", [0, -1, 1.5, True, "81", 9_007_199_254_740_992])
def test_remote_generation_must_be_positive_exact_integer(generation: object) -> None:
    request = copy.deepcopy(TARGET)
    request["expected_generation"]["descriptor"]["generation"] = generation
    assert not validator("SyncTargetRequest").is_valid(request)


@pytest.mark.unit
def test_native_catalog_fixture_matches_real_python_response_serialization() -> None:
    created = datetime(2026, 9, 8, tzinfo=UTC)
    tenant = TenantResponse(
        id="remote-tenant",
        name="Remote tenant",
        slug="remote",
        owner_id="remote-actor",
        created_at=created,
    )
    project = ProjectResponse(
        id="remote-project",
        tenant_id=tenant.id,
        name="Remote project",
        owner_id="remote-actor",
        created_at=created,
    )
    expected = {
        "tenants": TenantListResponse(tenants=[tenant], total=1, page=1, page_size=100).model_dump(
            mode="json"
        ),
        "projects": ProjectListResponse(
            projects=[project], total=1, page=1, page_size=100
        ).model_dump(mode="json"),
    }
    path = (
        ROOT
        / "agi-stack/apps/desktop/sidecar/src/local_runtime/knowledge_authority_v2"
        / "sync_catalog_fixture.json"
    )
    assert json.loads(path.read_text()) == expected
