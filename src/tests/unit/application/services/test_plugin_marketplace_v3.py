"""Persistence and resource ownership tests for the unified marketplace."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.application.services.plugin_marketplace_v3 import MarketplaceV3Error, PluginMarketplaceV3
from src.infrastructure.adapters.secondary.persistence.models import Skill, SkillVersion
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)

pytestmark = pytest.mark.unit

PACKAGE = {
    "descriptor": {
        "id": "example",
        "name": "Example",
        "description": "A test skill",
        "version": "1.0.0",
        "publisher": "MemStack",
        "source_id": "curated",
        "format": "codex",
        "category": "development",
        "capabilities": ["skills"],
        "targets": ["cloud", "local"],
        "permissions": ["skills:register"],
        "compatible": True,
        "reasons": [],
    },
    "resources": {
        "skills": [
            {
                "name": "example-skill",
                "description": "Testing",
                "content": "# Example",
                "path": "skills/example/SKILL.md",
            }
        ],
        "mcp_servers": {},
        "hooks": [],
        "apps": {},
    },
    "digest": "sha256:test",
}


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda connection: MarketplaceRecordV3.__table__.create(connection))
        await conn.run_sync(lambda connection: Skill.__table__.create(connection))
        await conn.run_sync(lambda connection: SkillVersion.__table__.create(connection))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def service(db, monkeypatch):
    monkeypatch.setenv("PLUGIN_MARKETPLACE_CURATED_DIRECTORY", "/test-fixture")
    instance = PluginMarketplaceV3(db, "tenant-a", "project-a")
    instance.packages = AsyncMock(return_value=[copy.deepcopy(PACKAGE)])
    return instance


async def install_fixture(service):
    preview = await service.preflight("curated", "example")
    return await service.install(preview["id"], preview["permissions"], "install-1")


async def test_install_requires_explicit_permissions_and_is_idempotent(service):
    preview = await service.preflight("curated", "example")
    with pytest.raises(MarketplaceV3Error, match="permissions"):
        await service.install(preview["id"], [], "install-1")
    installed = await service.install(preview["id"], preview["permissions"], "install-1")
    assert installed["status"] == "downloaded"
    assert await service.install(preview["id"], preview["permissions"], "install-1") == installed
    assert len(await service.records("installation")) == 1


async def test_scope_isolation_blocks_foreign_preflights_and_installations(service, db):
    installed = await install_fixture(service)
    foreign = PluginMarketplaceV3(db, "tenant-b", "project-a")
    assert await foreign.records("installation") == []
    with pytest.raises(MarketplaceV3Error, match="scope"):
        await foreign.mutate(installed["id"], "enable", {"idempotency_key": "foreign"})
    other_project = PluginMarketplaceV3(db, "tenant-a", "project-b")
    assert await other_project.records("installation") == []


async def test_enable_disable_uninstall_use_native_skill_registry(service, db):
    installed = await install_fixture(service)
    result = await service.mutate(installed["id"], "enable", {"idempotency_key": "enable-1"})
    assert result["status"] == "enabled"
    skill = await db.scalar(select(Skill).where(Skill.name == "example-skill"))
    assert skill.status == "active"
    assert skill.metadata_json["marketplace_installation_id"] == installed["id"]
    result = await service.mutate(installed["id"], "disable", {"idempotency_key": "disable-1"})
    assert result["status"] == "disabled"
    assert skill.status == "disabled"
    result = await service.mutate(installed["id"], "uninstall", {"idempotency_key": "remove-1"})
    assert result["status"] == "uninstalled"
    assert await db.scalar(select(Skill).where(Skill.name == "example-skill")) is None


async def test_user_skill_is_never_overwritten(service, db):
    db.add(
        Skill(
            id="user-skill",
            tenant_id="tenant-a",
            project_id="project-a",
            name="example-skill",
            description="User owned",
            tools=[],
            status="active",
            scope="project",
            full_content="User content",
        )
    )
    await db.flush()
    installed = await install_fixture(service)
    result = await service.mutate(installed["id"], "enable", {"idempotency_key": "enable-1"})
    assert result["status"] == "failed"
    assert (await db.get(Skill, "user-skill")).full_content == "User content"
    assert (await db.get(Skill, "user-skill")).status == "active"


async def test_failed_update_preserves_enabled_version(service, db):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    with pytest.raises(MarketplaceV3Error):
        await service.mutate(installed["id"], "update", {"idempotency_key": "update"})
    row = await service.record(installed["id"], "installation")
    assert row.payload["version"] == "1.0.0"
    assert row.payload["status"] == "enabled"
    assert (await db.scalar(select(Skill))).status == "active"


async def test_source_removal_requires_uninstall_and_server_local_import_is_rejected(service):
    with pytest.raises(MarketplaceV3Error, match="filesystem"):
        await service.add_source(
            {"name": "bad", "kind": "local", "location": "/etc", "trusted": True}
        )
    with pytest.raises(MarketplaceV3Error, match="HTTPS"):
        await service.add_source(
            {"name": "bad", "kind": "git", "location": "file:///etc", "trusted": True}
        )


async def test_persistence_survives_new_service_instance(service, db):
    installed = await install_fixture(service)
    await db.commit()
    reloaded = PluginMarketplaceV3(db, "tenant-a", "project-a")
    assert (
        reloaded.installation_view((await reloaded.record(installed["id"], "installation")).payload)
        == installed
    )


async def test_untrusted_source_cannot_preflight(service):
    source = await service.add_source(
        {
            "name": "untrusted",
            "kind": "https",
            "location": "https://example.com/catalog.json",
            "trusted": False,
        }
    )
    with pytest.raises(MarketplaceV3Error, match="trust"):
        await service.preflight(source["id"], "example")


async def test_update_stages_candidate_and_switches_only_after_activation(service, db):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    package = copy.deepcopy(PACKAGE)
    package["descriptor"]["version"] = "2.0.0"
    package["resources"]["skills"][0]["content"] = "# Version two"
    service.packages.return_value = [package]
    preview = await service.preflight("curated", "example", "2.0.0")
    updated = await service.mutate(
        installed["id"],
        "update",
        {
            "idempotency_key": "update",
            "preflight_id": preview["id"],
            "approved_permissions": preview["permissions"],
        },
    )
    assert updated["version"] == "2.0.0"
    assert updated["status"] == "enabled"
    skills = list(await db.scalars(select(Skill)))
    assert len(skills) == 1
    assert skills[0].name == "example-skill"
    assert skills[0].full_content == "# Version two"
    assert skills[0].metadata_json["marketplace_installation_id"] == installed["id"]


async def test_failed_candidate_keeps_old_skill_active(service, db):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    package = copy.deepcopy(PACKAGE)
    package["descriptor"]["version"] = "2.0.0"
    package["resources"]["mcp_servers"] = {"demo": {"url": "https://example.com/mcp"}}
    service.packages.return_value = [package]
    preview = await service.preflight("curated", "example", "2.0.0")
    with pytest.raises(MarketplaceV3Error, match="unchanged"):
        await service.mutate(
            installed["id"],
            "update",
            {
                "idempotency_key": "update",
                "preflight_id": preview["id"],
                "approved_permissions": preview["permissions"],
            },
        )
    assert (await db.scalar(select(Skill))).full_content == "# Example"
    assert (await db.scalar(select(Skill))).status == "active"
    assert (await service.record(installed["id"], "installation")).payload["version"] == "1.0.0"


async def test_configure_stores_ciphertext_and_never_returns_credentials(service, monkeypatch):
    from types import SimpleNamespace

    from src.infrastructure.plugins import marketplace_credentials
    from src.infrastructure.security.encryption_service import EncryptionService

    encryption = EncryptionService("12" * 32)
    monkeypatch.setattr(
        marketplace_credentials,
        "get_settings",
        lambda: SimpleNamespace(llm_encryption_key="12" * 32),
    )
    monkeypatch.setattr(marketplace_credentials, "get_encryption_service", lambda: encryption)
    installed = await install_fixture(service)
    result = await service.mutate(
        installed["id"],
        "configure",
        {"idempotency_key": "configure", "credentials": {"TOKEN": "test-value"}},
    )
    assert "test-value" not in str(result)
    payload = (await service.record(installed["id"], "installation")).payload
    assert "test-value" not in str(payload)
    assert marketplace_credentials.open_transport(payload["configuration"])["TOKEN"] == "test-value"
    transport = marketplace_credentials.configure_transport(
        {"headers": {"Authorization": "Bearer ${user_config.TOKEN}"}}, payload["configuration"]
    )
    assert "test-value" not in str(transport)
    assert (
        marketplace_credentials.open_transport(transport)["headers"]["Authorization"]
        == "Bearer test-value"
    )


async def test_switch_conflict_restores_old_version_without_overwriting_user_skill(service, db):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    db.add(
        Skill(
            id="unrelated",
            tenant_id="tenant-a",
            project_id="project-a",
            name="user-owned",
            description="User",
            tools=[],
            status="active",
            scope="project",
            full_content="Preserve me",
        )
    )
    await db.flush()
    package = copy.deepcopy(PACKAGE)
    package["descriptor"]["version"] = "2.0.0"
    package["resources"]["skills"][0]["name"] = "user-owned"
    service.packages.return_value = [package]
    preview = await service.preflight("curated", "example", "2.0.0")
    with pytest.raises(MarketplaceV3Error, match="restored"):
        await service.mutate(
            installed["id"],
            "update",
            {
                "idempotency_key": "update",
                "preflight_id": preview["id"],
                "approved_permissions": preview["permissions"],
            },
        )
    skills = list(await db.scalars(select(Skill).order_by(Skill.name)))
    assert [(skill.name, skill.status) for skill in skills] == [
        ("example-skill", "active"),
        ("user-owned", "active"),
    ]
    assert (await service.record(installed["id"], "installation")).payload["version"] == "1.0.0"


async def test_native_mcp_and_app_lifecycle_uses_owned_server(service):
    from types import SimpleNamespace

    server = SimpleNamespace(id="owned-server", runtime_status="running")
    app = SimpleNamespace(
        id="owned-app", server_id=server.id, ui_metadata=SimpleNamespace(resource_uri="ui://demo")
    )
    runtime = SimpleNamespace(
        create_server=AsyncMock(return_value=server),
        update_server=AsyncMock(return_value=server),
        sync_server=AsyncMock(return_value=server),
        delete_server=AsyncMock(),
    )
    service.mcp = SimpleNamespace(
        runtime_service=runtime,
        tool_cache=SimpleNamespace(invalidate=lambda tenant: None),
        app_service=SimpleNamespace(
            list_apps=AsyncMock(return_value=[app]),
            resolve_resource=AsyncMock(return_value=SimpleNamespace(is_ready=True)),
        ),
    )
    package = copy.deepcopy(PACKAGE)
    package["descriptor"]["capabilities"] = ["skills", "mcp", "apps"]
    package["resources"]["mcp_servers"] = {"demo": {"url": "https://example.com/mcp"}}
    package["resources"]["apps"] = {"demo": {"mcp_server": "demo", "resource_uri": "ui://demo"}}
    service.packages.return_value = [package]
    installed = await install_fixture(service)
    enabled = await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    assert enabled["status"] == "enabled"
    runtime.create_server.assert_awaited_once()
    service.mcp.app_service.resolve_resource.assert_awaited_once_with("owned-app", "project-a")
    verified = await service.mutate(installed["id"], "verify", {"idempotency_key": "verify"})
    assert verified["status"] == "enabled"
    runtime.sync_server.assert_awaited_once_with("owned-server", "tenant-a")
    removed = await service.mutate(installed["id"], "uninstall", {"idempotency_key": "uninstall"})
    assert removed["status"] == "uninstalled"
    runtime.delete_server.assert_awaited_once_with("owned-server", "tenant-a")


async def test_install_job_is_durable_and_idempotent_across_service_instances(service, db):
    preview = await service.preflight("curated", "example")
    installed = await service.install(preview["id"], preview["permissions"], "job-install")
    job_id = installed["job_id"]
    await db.commit()
    restarted = PluginMarketplaceV3(db, "tenant-a", "project-a")
    job = await restarted.record(job_id, "operation")
    assert job.payload["status"] == "completed"
    assert job.payload["stage"] == "downloaded"
    assert job.payload["stages"] == ["requested", "downloaded"]
    replay = await restarted.install(preview["id"], preview["permissions"], "job-install")
    assert replay["job_id"] == job_id
    assert len(await restarted.records("operation")) == 1


async def test_failed_update_job_keeps_error_and_replay_does_not_report_success(service, db):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    with pytest.raises(MarketplaceV3Error, match="preflight"):
        await service.mutate(installed["id"], "update", {"idempotency_key": "failed-update"})
    await db.commit()
    restarted = PluginMarketplaceV3(db, "tenant-a", "project-a")
    installation = await restarted.record(installed["id"], "installation")
    assert installation.payload["status"] == "enabled"
    job = await restarted.record(installation.payload["job_id"], "operation")
    assert job.payload["status"] == "failed"
    assert job.payload["stage"] == "rolled_back"
    assert "preflight" in job.payload["error"]
    with pytest.raises(MarketplaceV3Error, match="preflight"):
        await restarted.mutate(installed["id"], "update", {"idempotency_key": "failed-update"})


async def test_install_key_rejects_changed_permissions(service):
    preview = await service.preflight("curated", "example")
    await service.install(preview["id"], preview["permissions"], "same-key")
    with pytest.raises(MarketplaceV3Error, match="different operation"):
        await service.install(
            preview["id"], [*preview["permissions"], "process:execute"], "same-key"
        )


async def test_mutation_key_rejects_changed_configuration_and_preflight(service, monkeypatch):
    from types import SimpleNamespace

    from src.infrastructure.plugins import marketplace_credentials
    from src.infrastructure.security.encryption_service import EncryptionService

    encryption = EncryptionService("34" * 32)
    monkeypatch.setattr(
        marketplace_credentials,
        "get_settings",
        lambda: SimpleNamespace(llm_encryption_key="34" * 32),
    )
    monkeypatch.setattr(marketplace_credentials, "get_encryption_service", lambda: encryption)
    installed = await install_fixture(service)
    await service.mutate(
        installed["id"],
        "configure",
        {"idempotency_key": "same-key", "credentials": {"TOKEN": "first"}},
    )
    with pytest.raises(MarketplaceV3Error, match="different operation"):
        await service.mutate(
            installed["id"],
            "configure",
            {"idempotency_key": "same-key", "credentials": {"TOKEN": "second"}},
        )
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    with pytest.raises(MarketplaceV3Error):
        await service.mutate(installed["id"], "update", {"idempotency_key": "update"})
    with pytest.raises(MarketplaceV3Error, match="different operation"):
        await service.mutate(
            installed["id"], "update", {"idempotency_key": "update", "preflight_id": "changed"}
        )
    operations = str([row.payload for row in await service.records("operation")])
    assert '"first"' not in operations and '"second"' not in operations


async def test_failed_candidate_after_registration_removes_owned_skill_after_commit(
    service, db, monkeypatch
):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    await db.commit()
    original = (await service.record(installed["id"], "installation")).payload
    original_skill_ids = list(original["owned_skills"])
    package = copy.deepcopy(PACKAGE)
    package["descriptor"]["version"] = "2.0.0"
    service.packages.return_value = [package]
    preview = await service.preflight("curated", "example", "2.0.0")
    activate = service._activate
    candidate_ids = []

    async def fail_after_registration(payload):
        await activate(payload)
        candidate_ids.extend(payload["owned_skills"])
        assert candidate_ids
        await db.flush()
        raise MarketplaceV3Error("Candidate resource verification failed")

    monkeypatch.setattr(service, "_activate", fail_after_registration)
    with pytest.raises(MarketplaceV3Error, match="current version is unchanged"):
        await service.mutate(
            installed["id"],
            "update",
            {
                "idempotency_key": "post-registration-failure",
                "preflight_id": preview["id"],
                "approved_permissions": preview["permissions"],
            },
        )
    await db.commit()
    db.expire_all()
    skills = list(await db.scalars(select(Skill)))
    assert [skill.id for skill in skills] == original_skill_ids
    assert skills[0].name == "example-skill"
    assert skills[0].status == "active"
    assert skills[0].metadata_json["marketplace_installation_id"] == installed["id"]
    restarted = PluginMarketplaceV3(db, "tenant-a", "project-a")
    restored = (await restarted.record(installed["id"], "installation")).payload
    assert restored["version"] == "1.0.0"
    assert restored["owned_skills"] == original_skill_ids


async def test_enable_resolves_owned_disabled_app_without_reactivating_foreign_apps(service):
    from types import SimpleNamespace

    owned = SimpleNamespace(
        id="owned-app",
        server_id="owned-server",
        ui_metadata=SimpleNamespace(resource_uri="ui://demo"),
    )
    foreign = SimpleNamespace(
        id="foreign-app",
        server_id="foreign-server",
        ui_metadata=SimpleNamespace(resource_uri="ui://demo"),
    )

    async def list_apps(project_id, include_disabled=False):
        assert project_id == "project-a"
        return [owned, foreign] if include_disabled else []

    service.mcp = SimpleNamespace(
        app_service=SimpleNamespace(
            list_apps=list_apps,
            resolve_resource=AsyncMock(return_value=SimpleNamespace(is_ready=True)),
        )
    )
    await service._verify_apps(
        {
            "owned_servers": ["owned-server"],
            "package": {"resources": {"apps": {"demo": {"resource_uri": "ui://demo"}}}},
        }
    )
    service.mcp.app_service.resolve_resource.assert_awaited_once_with("owned-app", "project-a")
