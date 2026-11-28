"""The deployable signed-package kernel starts without loading the legacy business composition."""

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.unit


async def test_production_kernel_requires_deployment_secret_before_database_start(monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from src.configuration.config import Settings, get_settings
    from src.host.transport import package_kernel

    settings = get_settings().model_copy(
        update={
            "environment": "production",
            "package_kernel_database_mode": "shared",
            "secret_key": Settings.model_fields["secret_key"].default,
        }
    )
    monkeypatch.setattr(package_kernel, "get_settings", lambda: settings)
    start = AsyncMock(side_effect=AssertionError("database startup was reached"))
    monkeypatch.setattr(package_kernel, "initialize_database", start)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        async with package_kernel._lifespan(FastAPI()):
            pytest.fail("production kernel served with its development key")
    start.assert_not_awaited()


def test_kernel_bootstrap_without_any_builtin_package() -> None:
    script = textwrap.dedent(
        """
        from importlib.abc import MetaPathFinder
        import sys

        class AbsentBusinessPackages(MetaPathFinder):
            def find_spec(self, fullname, *args):
                if fullname in {"plugins.business", "plugins.adapters"} or fullname in {
                    "src.infrastructure.adapters.primary.web.main",
                    "src.infrastructure.plugins.v2.production_bundle",
                    "src.infrastructure.plugins.v2.builtin_modules",
                    "src.infrastructure.graph.native_graph_adapter",
                    "plugins.business.agent.engine.react.react_agent",
                }:
                    raise ModuleNotFoundError(fullname)

        sys.meta_path.insert(0, AbsentBusinessPackages())
        from src.host.transport.package_kernel import create_app
        app = create_app()
        paths = app.openapi()["paths"]
        assert "/api/v1/platform-plugins/v2/optional-business/install" in paths
        assert "/api/v1/auth/token" in paths
        assert "/api/v1/agent/conversations/{conversation_id}/local-runs" in paths
        assert "/api/v1/platform-plugins/v2/optional-business/npm/resolve" in paths
        assert all(route.path != "/api/v1/agent/ws" for route in app.routes)
        """
    )
    subprocess.run([sys.executable, "-c", script], check=True)


async def test_kernel_rejects_an_operation_pinned_to_a_full_host_generation() -> None:
    from httpx import ASGITransport, AsyncClient

    from src.host.transport.package_kernel import create_app
    from src.infrastructure.plugins.v2.boundary import IF_PLUGIN_GENERATION_HEADER_V2

    async with AsyncClient(transport=ASGITransport(create_app()), base_url="http://kernel") as http:
        response = await http.post(
            "/api/v1/platform-plugins/v2/optional-business/inspect",
            headers={IF_PLUGIN_GENERATION_HEADER_V2: "sha256:" + "1" * 64},
            json={"tenant_id": "t", "project_id": "p", "archive_base64": "YQ=="},
        )
    assert response.status_code == 409


async def test_project_picker_uses_persisted_memberships_and_roles(db_session):
    from sqlalchemy import update

    from src.host.identity.project_package_scope import (
        projects_for_package_management,
    )
    from src.infrastructure.adapters.secondary.persistence.models import (
        Project,
        Tenant,
        User,
        UserProject,
        UserTenant,
    )

    user = User(id="u", email="user@example.test", hashed_password="unused", is_active=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(Tenant(id="t", name="T", slug="tenant", owner_id=user.id))
    await db_session.flush()
    for key in ("p", "other"):
        db_session.add(Project(id=key, name=key, tenant_id="t", owner_id=user.id))
    await db_session.flush()
    db_session.add(UserProject(id="project-member", user_id=user.id, project_id="p", role="owner"))
    await db_session.commit()
    assert not await projects_for_package_management(user, db_session)
    user.is_superuser = True
    await db_session.commit()
    (only,) = await projects_for_package_management(user, db_session)
    assert only.project_id == "p" and not only.can_manage and only.can_execute
    db_session.add(UserTenant(id="tenant-member", user_id=user.id, tenant_id="t", role="member"))
    await db_session.commit()
    for role, can_manage, can_execute in (
        ("owner", True, True),
        ("admin", True, True),
        ("member", False, True),
        ("viewer", False, False),
    ):
        await db_session.execute(
            update(UserProject).where(UserProject.id == "project-member").values(role=role)
        )
        await db_session.commit()
        (only,) = await projects_for_package_management(user, db_session)
        assert only.project_id == "p" and only.tenant_id == "t"
        assert (only.can_manage, only.can_execute) == (can_manage, can_execute)
