"""Use the project search HTTP entry with a real loopback Cohere transport and signed Wasm."""

import base64
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.routers import enhanced_search
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.infrastructure.llm import project_cohere_rerank
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping
from src.infrastructure.security.encryption_service import EncryptionService
from src.tests.integration import package_gateway
from src.tests.integration.signed_wasm_releases import build_upgrade_pair
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
gateway_binary = package_gateway.gateway_binary
pytestmark = pytest.mark.integration
PLUGIN = "memstack-cohere-rerank"


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    package = Path(__file__).resolve().parents[3] / "plugins/adapters/models/cohere"
    return build_upgrade_pair(
        package,
        tmp_path_factory.mktemp("cohere-publisher"),
        "MAX_CHUNKS_PER_DOCUMENT: u32 = 1",
        "MAX_CHUNKS_PER_DOCUMENT: u32 = 2",
    )


@pytest.fixture
def cohere_endpoint():
    key = secrets.token_urlsafe(32)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/v1/rerank" or self.headers.get("Authorization") != f"Bearer {key}":
                self.send_error(403)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            top = 0 if body["max_chunks_per_doc"] == 1 else 1
            raw = json.dumps(
                {
                    "id": "fixture",
                    "results": [
                        {"index": top, "relevance_score": 0.9},
                        {"index": 1 - top, "relevance_score": 0.4},
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", key, calls
        finally:
            server.shutdown()
            thread.join(timeout=5)


async def _configure_search(client, db, public, endpoint, key, monkeypatch, tmp_path):
    app = client._transport.app
    app.include_router(enhanced_search.router)

    async def authority():
        graph = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    {"type": "episode", "content": "alpha", "uuid": "a"},
                    {"type": "episode", "content": "beta", "uuid": "b"},
                ]
            )
        )
        return SimpleNamespace(db=db, services=SimpleNamespace(graph_service=graph))

    app.dependency_overrides[enhanced_search.search_application_authority_dependency_v2] = authority
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public.decode(),)
    pem = tmp_path / "rerank.pem"
    pem.write_bytes(public)
    monkeypatch.setattr(get_settings(), "plugin_marketplace_trusted_key_files", (pem,))
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    cipher = EncryptionService(secrets.token_hex(32))
    monkeypatch.setattr(project_cohere_rerank, "get_encryption_service", lambda: cipher)
    assigned = LLMProvider(
        id=uuid4(),
        name="cohere-fixture",
        provider_type="cohere",
        operation_type="rerank",
        reranker_model="rerank-english-v3.0",
        base_url=endpoint,
        api_key_encrypted=cipher.encrypt(key),
    )
    db.add(assigned)
    db.add(Tenant(id="other-tenant", name="Other", slug="other-rerank", owner_id="owner"))
    await db.flush()
    db.add(
        TenantProviderMapping(
            id=uuid4(), tenant_id="t", provider_id=assigned.id, operation_type="rerank", priority=1
        )
    )
    db.add(
        Project(
            id="q",
            tenant_id="other-tenant",
            name="Q",
            owner_id="owner",
            graph_config={"cohere_rerank_package": PLUGIN},
        )
    )
    db.add(UserTenant(id="ut-owner-other", tenant_id="other-tenant", user_id="owner", role="owner"))
    await db.flush()
    db.add(UserProject(id="up-owner-q", user_id="owner", project_id="q", role="owner"))
    project = await db.get(Project, "p")
    project.graph_config = {"cohere_rerank_package": PLUGIN}
    await db.commit()


async def test_search_reranking_uses_tenant_transport_and_one_signed_release(
    http, db_session, releases, cohere_endpoint, monkeypatch, tmp_path, gateway_binary
):
    client, users = http
    public, first, second = releases
    endpoint, key, calls = cohere_endpoint
    await _configure_search(client, db_session, public, endpoint, key, monkeypatch, tmp_path)
    async with package_gateway.gateway_client(gateway_binary, client._transport.app) as proxy:
        await _exercise_releases(proxy, users, first, second, calls)


async def _exercise_releases(client, users, first, second, calls):
    headers = {"Authorization": "Bearer " + users["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"

    async def install(tenant, project, raw):
        scope = {"project_id": project, "tenant_id": tenant}
        res = await client.post(
            base + "/install",
            headers=headers,
            json={
                **scope,
                "approved_permissions": ["tools.execute"],
                "archive_base64": base64.b64encode(raw).decode(),
            },
        )
        assert res.is_success, res.text
        res = await client.post(f"{base}/{PLUGIN}/enable", headers=headers, json=scope)
        assert res.is_success and res.json()["runtime_phase"] == "active", res.text

    async def search(project="p", tenant="t", user="owner"):
        return await client.post(
            "/api/v1/search-enhanced/advanced",
            headers={"Authorization": "Bearer " + users[user]},
            json={
                "query": "query in project",
                "project_id": project,
                "tenant_id": tenant,
                "limit": 2,
                "reranker": "https://untrusted.invalid",
            },
        )

    for raw, expected, chunks in ((first, "alpha", 1), (second, "beta", 2)):
        await install("t", "p", raw)
        response = await search()
        assert response.is_success, response.text
        assert response.json()["results"][0]["content"] == expected
        assert calls[-1]["max_chunks_per_doc"] == chunks
        assert calls[-1]["documents"] == ["alpha", "beta"]
        assert calls[-1]["model"] == "rerank-english-v3.0"
        assert calls[-1]["query"] == "query in project"
    res = await client.post(
        f"{base}/{PLUGIN}/rollback", headers=headers, json={"project_id": "p", "tenant_id": "t"}
    )
    assert res.is_success, res.text
    response = await search()
    assert (
        response.json()["results"][0]["content"] == "alpha" and calls[-1]["max_chunks_per_doc"] == 1
    )
    await install("other-tenant", "q", first)
    seen = len(calls)
    assert (await search("q", "other-tenant")).status_code == 503
    assert (await search("q", "other-tenant", user="viewer")).status_code == 403
    assert (await search("p", "other-tenant")).status_code == 400
    assert len(calls) == seen
