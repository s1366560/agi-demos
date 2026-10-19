"""Feature admission preserves HTTP contracts and refuses disabled scoped operations."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    feature_operation_v2 as admission,
    get_current_user,
)
from src.infrastructure.adapters.primary.web.dependencies.feature_operation_scope_v2 import (
    feature_operation_scopes_v2,
)
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2.feature_operations import (
    builtin_feature_owner_v2,
    feature_owner_v2,
)
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

pytestmark = pytest.mark.unit


class OperationPayload(BaseModel):
    tenant_id: str
    value: int


class ProjectSettingsPayload(BaseModel):
    name: str | None = None
    memory_rules: dict | None = None
    graph_config: dict | None = None


def _runtime(enabled: bool = True, *, entries: tuple | None = None) -> tuple[Mock, Mock]:
    service = Mock()
    service.initialize = AsyncMock()
    service.effective_snapshot = AsyncMock(
        return_value=SimpleNamespace(
            entries=entries
            or (SimpleNamespace(entry_id="builtin-web-feature-tenant-skills", enabled=enabled),)
        )
    )
    runtime = Mock(spec=ScopedProfileRuntimeV2)
    runtime.instances.return_value = service
    return runtime, service


@pytest.fixture
def scope_authorizer(monkeypatch):
    authorize = AsyncMock(side_effect=lambda _db, *, current_user, requested_scope: requested_scope)
    monkeypatch.setattr(admission, "resolve_plugin_read_scope_v2", authorize)
    return authorize


async def test_guard_preserves_body_request_and_response_then_reenables(scope_authorizer) -> None:
    app = FastAPI()
    runtime, service = _runtime(False)
    app.state.scoped_profile_runtime_v2 = runtime
    user = SimpleNamespace(id="u1", is_superuser=False)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    effects = []

    async def operation(
        payload: OperationPayload, request: Request, current_user=Depends(get_current_user)
    ) -> dict:
        effects.append(payload.value)
        return {"value": payload.value, "path": request.url.path, "actor": current_user.id}

    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="test",
                path="/operation",
                methods=("POST",),
                endpoint=operation,
                name="operation",
                feature_owner=feature_owner_v2("tenant-skills"),
            ),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.post(
            "/operation?tenant_id=spoofed&project_id=spoofed", json={"tenant_id": "t1", "value": 7}
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "feature_disabled"
        assert effects == []
        assert runtime.instances.call_args.args[0] == ScopeV2(
            kind=ScopeKindV2.TENANT, tenant_id="t1"
        )
        service.effective_snapshot.return_value.entries[0].enabled = True
        allowed = await client.post("/operation", json={"tenant_id": "t1", "value": 8})
        assert allowed.status_code == 200
        assert allowed.json() == {"value": 8, "path": "/operation", "actor": "u1"}
        invalid = await client.post("/operation", json={"tenant_id": "t1", "value": "invalid"})
        assert invalid.status_code == 422
        assert effects == [8]
    service.initialize.assert_awaited_with("u1")
    assert scope_authorizer.await_count == 2


async def test_shared_settings_checks_only_supplied_feature_fields_before_any_write(
    scope_authorizer,
) -> None:
    app = FastAPI()
    runtime, _service = _runtime(
        entries=(
            SimpleNamespace(entry_id="builtin-web-feature-project-settings", enabled=True),
            SimpleNamespace(entry_id="builtin-web-feature-project-memories", enabled=False),
            SimpleNamespace(entry_id="builtin-web-feature-project-graph", enabled=True),
        )
    )
    app.state.scoped_profile_runtime_v2 = runtime
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(id="p1", tenant_id="t1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    writes = []

    async def update_project(
        project_id: str,
        project_data: ProjectSettingsPayload,
        current_user=Depends(get_current_user),
    ) -> dict:
        writes.append(project_data.model_dump(exclude_unset=True))
        return {"updated": project_id}

    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-projects-http-routes",
                path="/projects/{project_id}",
                methods=("PUT",),
                endpoint=update_project,
                name="update_project",
            ),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        renamed = await client.put("/projects/p1", json={"name": "New name"})
        assert renamed.status_code == 200
        mixed = await client.put(
            "/projects/p1", json={"name": "Blocked rename", "memory_rules": {}}
        )
        assert mixed.status_code == 403
        assert mixed.json()["detail"]["code"] == "feature_disabled"
        graph = await client.put("/projects/p1", json={"graph_config": {"mode": "new"}})
        assert graph.status_code == 200
    assert writes == [{"name": "New name"}, {"graph_config": {"mode": "new"}}]


async def test_membership_denial_precedes_snapshot_lookup(scope_authorizer) -> None:
    runtime, service = _runtime()
    app = FastAPI()
    app.state.scoped_profile_runtime_v2 = runtime
    scope_authorizer.side_effect = RuntimeV2Error("scope_read_forbidden", "denied")
    with pytest.raises(RuntimeV2Error, match="denied"):
        await admission.require_feature_operation_v2(
            request=Request({"type": "http", "app": app}),
            db=AsyncMock(),
            current_user=SimpleNamespace(id="u1"),
            feature_ids=("tenant-skills",),
            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="other"),
        )
    service.initialize.assert_not_awaited()
    service.effective_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "entries,allowed",
    [
        ((SimpleNamespace(entry_id="unrelated", enabled=True),), False),
        ((SimpleNamespace(entry_id="builtin-web-default-routes", enabled=True),), True),
        (
            (
                SimpleNamespace(entry_id="builtin-web-default-routes", enabled=True),
                SimpleNamespace(entry_id="builtin-web-feature-tenant-skills", enabled=False),
            ),
            False,
        ),
        (
            (
                SimpleNamespace(entry_id="feature-group", enabled=False),
                SimpleNamespace(
                    entry_id="builtin-web-feature-tenant-skills",
                    enabled=True,
                    parent_entry_id="feature-group",
                ),
            ),
            False,
        ),
        (
            (
                SimpleNamespace(
                    entry_id="builtin-web-feature-tenant-skills",
                    enabled=True,
                    parent_entry_id="missing-parent",
                ),
            ),
            False,
        ),
    ],
)
async def test_only_explicit_legacy_owner_can_supply_missing_feature(
    entries, allowed, scope_authorizer
) -> None:
    runtime, _service = _runtime(entries=entries)
    app = FastAPI()
    app.state.scoped_profile_runtime_v2 = runtime

    async def invoke():
        await admission.require_feature_operation_v2(
            request=Request({"type": "http", "app": app}),
            db=AsyncMock(),
            current_user=SimpleNamespace(id="u1"),
            feature_ids=("tenant-skills",),
            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="t1"),
        )

    if allowed:
        await invoke()
    else:
        with pytest.raises(RuntimeV2Error) as error:
            await invoke()
        assert error.value.code == "feature_disabled"


async def test_resource_ancestry_rejects_spoofed_tenant_before_publication() -> None:
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(tenant_id="actual", project_id=None, scope="tenant")
    with pytest.raises(RuntimeV2Error) as error:
        await feature_operation_scopes_v2(
            db=db,
            current_user=SimpleNamespace(id="u1", is_superuser=False),
            owner=feature_owner_v2("tenant-skills", ("skill", "skill_id")),
            arguments={"tenant_id": "spoofed", "skill_id": "s1"},
        )
    assert error.value.code == "scope_resource_unavailable"


async def test_proxy_checks_feature_before_forwarding_and_preserves_stream_on_reenable(
    monkeypatch,
    scope_authorizer,
) -> None:
    from src.infrastructure.adapters.primary.web import workspace_core_routes as proxy

    app = FastAPI()
    runtime, service = _runtime(
        entries=(
            SimpleNamespace(
                entry_id="builtin-web-feature-project-blackboard",
                enabled=False,
            ),
        )
    )
    app.state.scoped_profile_runtime_v2 = runtime
    user = SimpleNamespace(id="u1", is_superuser=False)
    app.dependency_overrides[get_current_user] = lambda: user
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(id="p1", tenant_id="t1")

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(proxy, "async_session_factory", session)
    forwarded = []

    async def forward(request, values):
        forwarded.append((await request.body(), values["current_user"].id))
        return Response(b"accepted", status_code=201)

    monkeypatch.setattr(proxy, "_proxy_workspace_request", forward)

    async def original(
        tenant_id: str,
        project_id: str,
        request: Request,
        payload: dict,
        current_user=Depends(get_current_user),
    ) -> dict:
        raise AssertionError("proxy must never call the retired endpoint")

    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-workspace-core-http-routes",
                name="create_post",
                path="/tenants/{tenant_id}/projects/{project_id}/posts",
                methods=("POST",),
                endpoint=original,
                route_class_override=proxy.WorkspaceCoreProxyRoute,
            ),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.post(
            "/tenants/t1/projects/p1/posts",
            content=b"stream-data",
            headers={"X-Agent-Id": "agent-1"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "feature_disabled"
        assert forwarded == []
        service.effective_snapshot.return_value.entries[0].enabled = True
        allowed = await client.post("/tenants/t1/projects/p1/posts", content=b"stream-data")
        assert allowed.status_code == 201
        assert forwarded == [(b"stream-data", "u1")]


async def test_resource_project_uses_persisted_parent() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [
        SimpleNamespace(project_id="p1"),
        SimpleNamespace(id="p1", tenant_id="t1"),
    ]
    scopes = await feature_operation_scopes_v2(
        db=db,
        current_user=SimpleNamespace(id="u1", is_superuser=False),
        owner=feature_owner_v2("project-memories", ("memory", "memory_id")),
        arguments={"memory_id": "m1"},
    )
    assert scopes == (ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="t1", project_id="p1"),)


async def test_template_id_selects_its_persisted_scope_without_optional_query_fields() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [
        SimpleNamespace(tenant_id="t1", project_id="p1"),
        SimpleNamespace(id="p1", tenant_id="t1"),
    ]
    owner = builtin_feature_owner_v2("builtin-agent-http-routes", "update_template")
    assert owner is not None
    scopes = await feature_operation_scopes_v2(
        db=db,
        current_user=SimpleNamespace(id="u1", is_superuser=False),
        owner=owner,
        arguments={"template_id": "template-1"},
    )
    assert scopes == (ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="t1", project_id="p1"),)


async def test_aggregate_checks_each_authorized_project_instead_of_default_tenant() -> None:
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(
        all=lambda: [
            SimpleNamespace(id="p1", tenant_id="t1"),
            SimpleNamespace(id="p2", tenant_id="t2"),
        ]
    )
    scopes = await feature_operation_scopes_v2(
        db=db,
        current_user=SimpleNamespace(id="u1", is_superuser=False),
        owner=feature_owner_v2("project-graph", project_aggregate=True),
        arguments={},
    )
    assert {scope.project_id for scope in scopes} == {"p1", "p2"}


async def test_maintenance_without_project_refuses_a_disabled_aggregated_project(
    scope_authorizer,
) -> None:
    app = FastAPI()
    runtime, enabled = _runtime(
        entries=(SimpleNamespace(entry_id="builtin-web-feature-project-maintenance", enabled=True),)
    )
    _, disabled = _runtime(
        entries=(
            SimpleNamespace(entry_id="builtin-web-feature-project-maintenance", enabled=False),
        )
    )
    runtime.instances.side_effect = lambda scope: disabled if scope.project_id == "p2" else enabled
    app.state.scoped_profile_runtime_v2 = runtime
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(
        all=lambda: [
            SimpleNamespace(id="p1", tenant_id="t1"),
            SimpleNamespace(id="p2", tenant_id="t1"),
        ]
    )
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: "t1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="u1", is_superuser=False
    )
    effects = []

    async def get_maintenance_status(
        project_id: str | None = None, current_user=Depends(get_current_user)
    ) -> dict:
        effects.append(project_id)
        return {"projects": ["p1", "p2"]}

    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-maintenance-http-routes",
                path="/maintenance/status",
                methods=("GET",),
                endpoint=get_maintenance_status,
                name="get_maintenance_status",
            ),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.get("/maintenance/status")
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "feature_disabled"
        assert effects == []
        disabled.effective_snapshot.return_value.entries[0].enabled = True
        allowed = await client.get("/maintenance/status")
        assert allowed.status_code == 200
        assert allowed.json()["projects"] == ["p1", "p2"]
        assert effects == [None]


async def test_support_without_tenant_refuses_a_disabled_ticket_tenant_and_keeps_aggregation(
    scope_authorizer,
) -> None:
    app = FastAPI()
    runtime, enabled = _runtime(
        entries=(SimpleNamespace(entry_id="builtin-web-feature-project-support", enabled=True),)
    )
    _, disabled = _runtime(
        entries=(SimpleNamespace(entry_id="builtin-web-feature-project-support", enabled=False),)
    )
    runtime.instances.side_effect = lambda scope: disabled if scope.tenant_id == "t2" else enabled
    app.state.scoped_profile_runtime_v2 = runtime
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: ["t1", "t2"])
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: "t1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="u1", is_superuser=False
    )
    effects = []

    async def list_support_tickets(
        tenant_id: str | None = None, current_user=Depends(get_current_user)
    ) -> dict:
        effects.append(tenant_id)
        return {"tenants": [tenant_id] if tenant_id else ["t1", "t2"]}

    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-support-http-routes",
                path="/support/tickets",
                methods=("GET",),
                endpoint=list_support_tickets,
                name="list_support_tickets",
            ),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.get("/support/tickets")
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "feature_disabled"
        assert effects == []
        allowed = await client.get("/support/tickets?tenant_id=t1")
        assert allowed.status_code == 200
        assert allowed.json()["tenants"] == ["t1"]
        assert effects == ["t1"]
        disabled.effective_snapshot.return_value.entries[0].enabled = True
        aggregated = await client.get("/support/tickets")
        assert aggregated.status_code == 200
        assert aggregated.json()["tenants"] == ["t1", "t2"]
        assert effects == ["t1", None]


def test_shared_graph_features_are_independent_and_recovery_remains_accessible() -> None:
    graph = builtin_feature_owner_v2("builtin-graph-http-routes", "get_graph")
    entities = builtin_feature_owner_v2("builtin-graph-http-routes", "list_entities")
    communities = builtin_feature_owner_v2("builtin-graph-http-routes", "list_communities")
    assert graph.feature_ids == ("project-graph",)
    assert entities.feature_ids == ("project-entities",)
    assert communities.feature_ids == ("project-communities",)
    assert builtin_feature_owner_v2("builtin-projects-http-routes", "get_project") is None
    assert builtin_feature_owner_v2("builtin-tenants-http-routes", "list_tenants") is None
    assert (
        builtin_feature_owner_v2(
            "builtin-platform-plugins-http-routes", "apply_plugin_instances_v2"
        )
        is None
    )
