"""Fixed Cloud QA composition, canonical vectors, and actual runtime publication."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from scripts.cloud_knowledge_sync_acceptance_profile import (
    CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_ENTRIES as ENTRIES,
    CLOUD_KNOWLEDGE_SYNC_ACCEPTANCE_PROFILE as PROFILE,
    cloud_knowledge_sync_generation_vectors,
    include_cloud_knowledge_sync_acceptance,
)
from scripts.generate_plugin_protocol_v2 import _bootstrap_profile, _builtin_manifest, _schema
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_generation_v2 import (
    KNOWLEDGE_SYNC_GENERATION_HEADER as HEADER,
    cloud_knowledge_sync_generation_payload_v2,
    require_cloud_knowledge_sync_generation_v2,
)
from src.infrastructure.plugins.v2.boundary import PluginGenerationMiddlewareV2
from src.infrastructure.plugins.v2.builtin_cloud_knowledge_sync_http_routes import (
    CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import (
    ProfileDocumentV2,
    compose_profile_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    control_envelope_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]
CONTRIBUTION = ROOT / "config/plugin-profiles/memstack-cloud-knowledge-sync-acceptance.v2.yaml"


@pytest.fixture(scope="module")
def profiles():
    product = parse_profile_snapshot_v2(_bootstrap_profile(_builtin_manifest(_schema())))
    document = ProfileDocumentV2(profile_id=product.profile_id, entries=product.entries)
    accepted = include_cloud_knowledge_sync_acceptance(document, CONTRIBUTION)
    snapshot = compose_profile_v2(
        accepted, {manifest.plugin_id: manifest for manifest in product.manifests}, generation=1
    )
    return product, document, snapshot


def test_cloud_qa_changes_only_three_enabled_flags_and_its_profile_identity(profiles):
    product, _document, accepted = profiles
    old = profile_snapshot_v2_to_payload(product)
    new = profile_snapshot_v2_to_payload(accepted)
    assert old["profile_id"] == "memstack-default-v2" and new["profile_id"] == PROFILE
    assert old["manifests"] == new["manifests"]
    assert old["digest"] != new["digest"]
    for before, after in zip(old["entries"], new["entries"], strict=True):
        if before["entry_id"] in ENTRIES:
            assert before["enabled"] is False
            assert after == {**before, "enabled": True}
        else:
            assert after == before
    native = next(
        entry
        for entry in accepted.entries
        if entry.entry_id == "builtin-desktop-sidecar-knowledge-authority"
    )
    assert not native.enabled
    assert native.config == {"release_contract": "knowledge-and-sync-v1", "release_state": "closed"}
    assert (
        json.loads((ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text()) == old
    )


@pytest.mark.parametrize(
    "mutation",
    ["wrong_profile", "missing", "extra", "duplicate", "config", "scope", "inject", "patch"],
)
def test_contribution_cannot_change_authority_beyond_the_three_enabled_flags(
    profiles, tmp_path, mutation
):
    _product, document, _accepted = profiles
    candidate = yaml.safe_load(CONTRIBUTION.read_text())
    rows = candidate["profile"]["entries"]
    match mutation:
        case "wrong_profile":
            candidate["profile"]["id"] = "memstack-local-knowledge-acceptance-v2"
        case "missing":
            rows.pop()
        case "extra":
            rows.append({**deepcopy(rows[0]), "entry_id": "unexpected"})
        case "duplicate":
            rows.append(deepcopy(rows[0]))
        case "config":
            rows[0]["config"] = {"strategy": "other"}
        case "scope":
            rows[0]["scope"] = {"kind": "tenant", "tenant_id": "tenant"}
        case "inject":
            rows[0]["inject"] = {"unexpected": "service:other"}
        case "patch":
            candidate["profile"]["patches"] = [{"target": rows[0]["entry_id"], "remove": True}]
    path = tmp_path / "contribution.yaml"
    path.write_text(yaml.safe_dump(candidate))
    with pytest.raises(ValueError):
        include_cloud_knowledge_sync_acceptance(document, path)


def test_cloud_qa_rejects_a_base_that_already_enabled_sync_or_is_a_native_profile(profiles):
    _product, document, _accepted = profiles
    opened = replace(
        document,
        entries=tuple(
            replace(entry, enabled=True) if entry.entry_id in ENTRIES else entry
            for entry in document.entries
        ),
    )
    with pytest.raises(ValueError, match="only enable the closed"):
        include_cloud_knowledge_sync_acceptance(opened, CONTRIBUTION)
    native = replace(document, profile_id="memstack-knowledge-sync-acceptance-v2")
    with pytest.raises(ValueError, match="unpatched default"):
        include_cloud_knowledge_sync_acceptance(native, CONTRIBUTION)
    missing = replace(
        document,
        entries=tuple(entry for entry in document.entries if entry.entry_id not in ENTRIES),
    )
    with pytest.raises(ValueError, match="all three product"):
        include_cloud_knowledge_sync_acceptance(missing, CONTRIBUTION)


def test_vectors_use_standard_protocol_and_distinguish_template_from_runtime_identity(profiles):
    _product, _document, snapshot = profiles
    vectors = cloud_knowledge_sync_generation_vectors(snapshot)
    assert vectors == cloud_knowledge_sync_generation_vectors(snapshot)
    assert vectors["template_generation"] == 1
    assert vectors["template_digest"] == snapshot.digest
    assert [row["generation"] for row in vectors["descriptors"]] == [1, 81, 82]
    assert len({row["digest"] for row in vectors["descriptors"]}) == 3
    for expected in vectors["descriptors"]:
        projected = build_profile_snapshot_v2(
            profile_id=snapshot.profile_id,
            generation=expected["generation"],
            manifests=snapshot.manifests,
            entries=snapshot.entries,
        )
        validated = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(projected))
        assert validated.digest == expected["digest"]
    with pytest.raises(ValueError):
        cloud_knowledge_sync_generation_vectors(replace(snapshot, digest="0" * 64))


async def test_actual_host_uses_dynamic_qa_descriptor_and_rejects_template_header_after_publish(
    profiles,
):
    product, _document, snapshot = profiles
    vectors = cloud_knowledge_sync_generation_vectors(snapshot)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    async def publish(template, generation):
        projected = build_profile_snapshot_v2(
            profile_id=template.profile_id,
            generation=generation,
            manifests=template.manifests,
            entries=template.entries,
        )
        result = await host.apply(projected, control_envelope_v2(projected, version=generation))
        assert result.accepted
        async with await host.acquire() as active:
            builder = active.resolve(ROUTE_TABLE_BUILDER_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT))
            routes = tuple(
                item
                for item in builder.definitions
                if item.owner_entry_id == CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2
            )
        return host.current_distribution.descriptor.to_payload(), routes

    app = FastAPI()

    @app.get("/condition", dependencies=[Depends(require_cloud_knowledge_sync_generation_v2)])
    async def condition():
        return cloud_knowledge_sync_generation_payload_v2()

    app.add_middleware(PluginGenerationMiddlewareV2, host_provider=lambda _scope: host)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://qa.test"
        ) as client:
            old = None
            for expected in vectors["descriptors"]:
                descriptor, routes = await publish(snapshot, expected["generation"])
                assert descriptor == expected and len(routes) == 11
                if old is not None:
                    response = await client.get("/condition", headers={HEADER: json.dumps(old)})
                    assert response.status_code == 412, response.text
                current = {"contract_version": "1.0.0", "descriptor": descriptor}
                response = await client.get("/condition", headers={HEADER: json.dumps(current)})
                assert response.status_code == 200 and response.json() == current
                old = current
            descriptor, routes = await publish(product, 83)
            assert descriptor["profile_id"] == "memstack-default-v2" and not routes
    finally:
        await host.close()
