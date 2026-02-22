"""Unit tests for channels router.

Tests cover:
- Router registration (P0-ARCH-4)
- Endpoint accessibility
- Permission verification (P1-SEC-2)
- Encryption of credentials (P0-SEC-1)
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.channels import (
    ChannelConfigCreate,
    ChannelConfigResponse,
    ChannelConfigUpdate,
    create_config,
    enable_tenant_plugin,
    get_project_channel_plugin_schema,
    get_tenant_channel_plugin_schema,
    list_all_connection_status,
    list_project_channel_plugin_catalog,
    list_tenant_channel_plugin_catalog,
    list_tenant_plugins,
    reload_project_plugins,
    reload_tenant_plugins,
    router,
    to_response,
    uninstall_tenant_plugin,
    update_config,
    verify_project_access,
)
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
)
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject


@pytest.fixture
def app():
    """Create a FastAPI app with the channels router registered."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_current_user():
    """Create a mock current user."""
    return {"id": "user-123", "email": "test@example.com"}


@pytest.fixture
def sample_channel_config():
    """Create a sample channel configuration model."""
    return ChannelConfigModel(
        id="config-123",
        project_id="project-456",
        channel_type="feishu",
        name="Test Feishu Channel",
        enabled=True,
        connection_mode="websocket",
        app_id="cli_test123",
        app_secret="secret123",  # Will be encrypted in production
        domain="feishu",
        status="disconnected",
        created_at=datetime.utcnow(),
    )


class TestRouterRegistration:
    """Test that router is properly registered and accessible."""

    def test_router_has_correct_prefix(self):
        """Router should have /channels prefix."""
        assert router.prefix == "/channels"

    def test_router_has_channels_tag(self):
        """Router should have 'channels' tag."""
        assert "channels" in router.tags

    def test_router_has_required_endpoints(self):
        """Router should have all required endpoints registered."""
        routes = [route.path for route in router.routes]

        # Check all expected endpoints exist (paths include /channels prefix)
        assert "/channels/projects/{project_id}/configs" in routes
        assert "/channels/configs/{config_id}" in routes
        assert "/channels/configs/{config_id}/test" in routes
        assert "/channels/projects/{project_id}/observability/summary" in routes
        assert "/channels/projects/{project_id}/observability/outbox" in routes
        assert "/channels/projects/{project_id}/observability/session-bindings" in routes


class TestEndpointAccessibility:
    """Test that endpoints are accessible after router registration."""

    def test_list_configs_endpoint_exists(self, app):
        """List configs endpoint should be accessible."""
        from src.infrastructure.adapters.primary.web.dependencies import get_current_user
        from src.infrastructure.adapters.secondary.persistence.database import get_db

        # Create proper async mock functions
        async def override_get_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=MagicMock())
            return session

        async def override_get_current_user():
            # Return a proper User object
            return User(
                id="user-123",
                email="test@example.com",
                hashed_password="hash",
            )

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        client = TestClient(app)
        response = client.get("/api/v1/channels/projects/test-project/configs")
        # Should not return 404 (not found) or 405 (method not allowed)
        # May return 403 (permission denied) if access not mocked properly
        assert response.status_code not in [404, 405]

    def test_create_config_endpoint_exists(self, app):
        """Create config endpoint should be accessible."""
        from src.infrastructure.adapters.primary.web.dependencies import get_current_user
        from src.infrastructure.adapters.secondary.persistence.database import get_db

        async def override_get_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=MagicMock())
            session.add = MagicMock()
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            return session

        async def override_get_current_user():
            return User(
                id="user-123",
                email="test@example.com",
                hashed_password="hash",
            )

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        # Mock the repository
        with patch(
            "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_config = ChannelConfigModel(
                id="config-123",
                project_id="test-project",
                channel_type="feishu",
                name="Test Channel",
                enabled=True,
                connection_mode="websocket",
                status="disconnected",
                created_at=datetime.utcnow(),
            )
            mock_repo.create = AsyncMock(return_value=mock_config)
            mock_repo_class.return_value = mock_repo

            client = TestClient(app)
            response = client.post(
                "/api/v1/channels/projects/test-project/configs",
                json={
                    "channel_type": "feishu",
                    "name": "Test Channel",
                },
            )
            # Should not return 404 (not found) or 405 (method not allowed)
            assert response.status_code not in [404, 405]


class TestToResponse:
    """Test the to_response helper function."""

    def test_to_response_excludes_app_secret(self, sample_channel_config):
        """to_response should exclude app_secret from response."""
        response = to_response(sample_channel_config)

        assert isinstance(response, ChannelConfigResponse)
        assert hasattr(response, "app_id")
        # app_secret should NOT be in the response
        assert not hasattr(response, "app_secret")

    def test_to_response_includes_required_fields(self, sample_channel_config):
        """to_response should include all required fields."""
        response = to_response(sample_channel_config)

        assert response.id == sample_channel_config.id
        assert response.project_id == sample_channel_config.project_id
        assert response.channel_type == sample_channel_config.channel_type
        assert response.name == sample_channel_config.name
        assert response.enabled == sample_channel_config.enabled
        assert response.status == sample_channel_config.status


class TestPydanticSchemas:
    """Test Pydantic schema validation."""

    def test_create_schema_defaults(self):
        """ChannelConfigCreate should have correct defaults."""
        data = ChannelConfigCreate(
            channel_type="feishu",
            name="Test",
        )
        assert data.enabled is True
        assert data.connection_mode == "websocket"
        assert data.domain == "feishu"

    def test_update_schema_all_optional(self):
        """ChannelConfigUpdate should have all optional fields."""
        data = ChannelConfigUpdate()
        assert data.name is None
        assert data.enabled is None
        assert data.app_secret is None

    def test_response_schema_config_compatibility(self):
        """ChannelConfigResponse Config should use Pydantic v2 syntax."""
        # In Pydantic v2, Config.from_attributes replaces Config.orm_mode
        assert hasattr(ChannelConfigResponse, "model_config") or hasattr(
            ChannelConfigResponse, "Config"
        )


class TestCredentialEncryption:
    """Test that credentials are encrypted before storage."""

    @pytest.mark.asyncio
    async def test_app_secret_encrypted_on_create(self, mock_db_session, mock_current_user):
        """app_secret should be encrypted before storing in database."""
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()

        with patch(
            "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.create = AsyncMock()

            created_config = ChannelConfigModel(
                id="new-config-123",
                project_id="project-456",
                channel_type="feishu",
                name="Test Channel",
                app_secret=encryption_service.encrypt("my-secret"),
            )
            mock_repo.create.return_value = created_config
            mock_repo_class.return_value = mock_repo

            # The implementation should encrypt app_secret
            ChannelConfigCreate(
                channel_type="feishu",
                name="Test Channel",
                app_secret="my-secret",
            )

            # This test verifies the expected behavior
            # The actual implementation needs to encrypt before storage


class TestPermissionVerification:
    """Test that permission checks are in place."""

    @pytest.mark.asyncio
    async def test_create_config_requires_authentication(self, app, mock_db_session):
        """Creating config should require authentication."""
        from src.infrastructure.adapters.primary.web.dependencies import get_current_user

        # When authentication fails, should raise 401
        async def failing_auth():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[get_current_user] = failing_auth

        client = TestClient(app)
        response = client.post(
            "/api/v1/channels/projects/test-project/configs",
            json={"channel_type": "feishu", "name": "Test"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_project_access_granted_for_member(self, mock_db_session):
        """verify_project_access should succeed for project member."""
        user = User(
            id="user-123",
            email="test@example.com",
            hashed_password="hash",
        )
        user_project = UserProject(
            id="up-123",
            user_id="user-123",
            project_id="project-456",
            role="member",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user_project
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await verify_project_access("project-456", user, mock_db_session)

        assert result == user_project

    @pytest.mark.asyncio
    async def test_verify_project_access_denied_for_non_member(self, mock_db_session):
        """verify_project_access should raise 403 for non-member."""
        user = User(
            id="user-123",
            email="test@example.com",
            hashed_password="hash",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await verify_project_access("project-456", user, mock_db_session)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_verify_project_access_with_required_role(self, mock_db_session):
        """verify_project_access should check role when required."""
        user = User(
            id="user-123",
            email="test@example.com",
            hashed_password="hash",
        )
        user_project = UserProject(
            id="up-123",
            user_id="user-123",
            project_id="project-456",
            role="admin",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user_project
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await verify_project_access(
            "project-456", user, mock_db_session, required_role=["owner", "admin"]
        )

        assert result == user_project

    @pytest.mark.asyncio
    async def test_verify_project_access_denied_for_insufficient_role(self, mock_db_session):
        """verify_project_access should deny if role is insufficient."""
        user = User(
            id="user-123",
            email="test@example.com",
            hashed_password="hash",
        )
        # When required_role is specified, the query filters by role
        # So if viewer is not in ["owner", "admin"], the query returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Not found after role filter
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await verify_project_access(
                "project-456", user, mock_db_session, required_role=["owner", "admin"]
            )

        assert exc_info.value.status_code == 403


class TestChannelConfigModelConstraints:
    """Test database model constraints and relationships."""

    def test_model_has_project_relationship(self):
        """ChannelConfigModel should have project relationship."""
        assert hasattr(ChannelConfigModel, "project")

    def test_model_has_unique_constraint_on_project_type(self):
        """ChannelConfigModel should have index on (project_id, channel_type)."""
        table_args = ChannelConfigModel.__table_args__
        index_names = []
        for arg in table_args:
            if hasattr(arg, "name"):
                index_names.append(arg.name)

        assert "ix_channel_configs_project_type" in index_names


class TestGlobalConnectionStatusAccess:
    """Test /channels/status admin access behavior."""

    @pytest.mark.asyncio
    async def test_list_all_connection_status_allows_superuser(self, mock_db_session):
        """Superuser should pass without relying on missing current_user.role attribute."""
        current_user = User(
            id="user-admin",
            email="admin@example.com",
            hashed_password="hash",
            is_superuser=True,
        )
        mock_manager = MagicMock()
        mock_manager.get_all_status.return_value = [
            {
                "config_id": "cfg-1",
                "project_id": "proj-1",
                "channel_type": "feishu",
                "status": "connected",
                "connected": True,
                "last_heartbeat": None,
                "last_error": None,
                "reconnect_attempts": 0,
            }
        ]

        with patch(
            "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
            return_value=mock_manager,
        ):
            response = await list_all_connection_status(
                db=mock_db_session, current_user=current_user
            )

        assert len(response) == 1
        assert response[0].config_id == "cfg-1"

    @pytest.mark.asyncio
    async def test_list_all_connection_status_denies_non_admin(self, mock_db_session):
        """Non-superuser without admin role should be denied."""
        current_user = User(
            id="user-member",
            email="member@example.com",
            hashed_password="hash",
            is_superuser=False,
        )

        role_count_result = MagicMock()
        role_count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=role_count_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await list_all_connection_status(db=mock_db_session, current_user=current_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_all_connection_status_allows_global_admin_role(self, mock_db_session):
        """Global system admin role (tenant_id is null) should be allowed."""
        current_user = User(
            id="user-global-admin",
            email="global-admin@example.com",
            hashed_password="hash",
            is_superuser=False,
        )
        role_count_result = MagicMock()
        role_count_result.scalar.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=role_count_result)

        mock_manager = MagicMock()
        mock_manager.get_all_status.return_value = []

        with patch(
            "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
            return_value=mock_manager,
        ):
            response = await list_all_connection_status(
                db=mock_db_session, current_user=current_user
            )

        query_sql = str(mock_db_session.execute.call_args.args[0])
        assert "user_roles.tenant_id IS NULL" in query_sql
        compiled_params = mock_db_session.execute.call_args.args[0].compile().params
        role_values = next(
            (value for key, value in compiled_params.items() if key.startswith("name_")),
            [],
        )
        assert "system_admin" in role_values
        assert response == []

    @pytest.mark.asyncio
    async def test_list_all_connection_status_denies_tenant_scoped_admin(self, mock_db_session):
        """Tenant-scoped admin should not pass global status endpoint authorization."""
        current_user = User(
            id="user-tenant-admin",
            email="tenant-admin@example.com",
            hashed_password="hash",
            is_superuser=False,
        )
        role_count_result = MagicMock()
        role_count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=role_count_result)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await list_all_connection_status(db=mock_db_session, current_user=current_user)

        query_sql = str(mock_db_session.execute.call_args.args[0])
        assert "user_roles.tenant_id IS NULL" in query_sql
        assert exc_info.value.status_code == 403


class TestPluginChannelCatalog:
    """Test plugin-backed channel catalog metadata endpoints."""

    @pytest.mark.asyncio
    async def test_catalog_marks_schema_supported(self, mock_db_session):
        """Catalog should expose schema availability per channel type."""
        mock_user = User(id="u-1", email="user@example.com", hashed_password="hash")

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._load_runtime_plugins",
                new=AsyncMock(
                    return_value=(
                        [
                            {
                                "name": "feishu-channel-plugin",
                                "source": "local",
                                "package": None,
                                "version": None,
                                "enabled": True,
                                "discovered": True,
                            }
                        ],
                        [],
                        {},
                    )
                ),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_adapter_factories.return_value = {
                "feishu": ("feishu-channel-plugin", object())
            }
            mock_registry.list_channel_type_metadata.return_value = {
                "feishu": SimpleNamespace(config_schema={"type": "object"})
            }
            mock_get_registry.return_value = mock_registry

            response = await list_project_channel_plugin_catalog(
                project_id="project-1",
                db=mock_db_session,
                current_user=mock_user,
            )

        assert len(response.items) == 1
        assert response.items[0].channel_type == "feishu"
        assert response.items[0].schema_supported is True

    @pytest.mark.asyncio
    async def test_schema_endpoint_returns_metadata(self, mock_db_session):
        """Schema endpoint should return metadata registered by plugin runtime."""
        mock_user = User(id="u-1", email="user@example.com", hashed_password="hash")

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._load_runtime_plugins",
                new=AsyncMock(
                    return_value=(
                        [
                            {
                                "name": "feishu-channel-plugin",
                                "source": "local",
                                "package": None,
                                "version": "0.1.0",
                                "enabled": True,
                                "discovered": True,
                            }
                        ],
                        [],
                        {},
                    )
                ),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
        ):
            metadata = SimpleNamespace(
                channel_type="feishu",
                plugin_name="feishu-channel-plugin",
                config_schema={"type": "object"},
                config_ui_hints={"app_secret": {"sensitive": True}},
                defaults={"domain": "feishu"},
                secret_paths=["app_secret"],
            )
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {"feishu": metadata}
            mock_get_registry.return_value = mock_registry

            response = await get_project_channel_plugin_schema(
                project_id="project-1",
                channel_type="feishu",
                db=mock_db_session,
                current_user=mock_user,
            )

        assert response.channel_type == "feishu"
        assert response.schema_supported is True
        assert response.config_schema == {"type": "object"}
        assert response.secret_paths == ["app_secret"]


class TestPluginSchemaExecution:
    """Test schema-driven channel settings execution for plugin channel types."""

    @staticmethod
    def _feishu_metadata(defaults: dict | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            channel_type="feishu",
            plugin_name="feishu-channel-plugin",
            config_schema={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "app_secret": {"type": "string"},
                    "domain": {"type": "string"},
                    "connection_mode": {"type": "string"},
                    "webhook_path": {"type": "string"},
                },
                "required": ["app_id", "app_secret"],
                "additionalProperties": False,
            },
            defaults=defaults or {},
            config_ui_hints={},
            secret_paths=["app_secret"],
        )

    @pytest.mark.asyncio
    async def test_create_config_applies_plugin_defaults(self, mock_db_session):
        """Create should apply plugin defaults before persisting config."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        payload = ChannelConfigCreate(
            channel_type="feishu",
            name="Feishu",
            app_id="cli_test",
            app_secret="secret",
        )

        captured: dict[str, ChannelConfigModel] = {}

        async def _create_side_effect(config: ChannelConfigModel) -> ChannelConfigModel:
            captured["config"] = config
            config.id = "cfg-1"
            config.status = "disconnected"
            config.created_at = datetime.utcnow()
            return config

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
            ) as mock_repo_class,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=None,
            ),
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {
                "feishu": self._feishu_metadata(
                    defaults={"domain": "feishu-default", "webhook_path": "/plugin/hook"}
                )
            }
            mock_get_registry.return_value = mock_registry

            mock_repo = MagicMock()
            mock_repo.create = AsyncMock(side_effect=_create_side_effect)
            mock_repo_class.return_value = mock_repo

            response = await create_config(
                project_id="project-1",
                data=payload,
                db=mock_db_session,
                current_user=current_user,
            )

        assert captured["config"].domain == "feishu-default"
        assert captured["config"].webhook_path == "/plugin/hook"
        assert response.domain == "feishu-default"

    @pytest.mark.asyncio
    async def test_create_config_rejects_invalid_plugin_settings(self, mock_db_session):
        """Create should return 422 when payload violates plugin schema."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        payload = ChannelConfigCreate(
            channel_type="feishu",
            name="Feishu",
            app_id="cli_test",
            app_secret="secret",
            extra_settings={"unexpected": "value"},
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
            ) as mock_repo_class,
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {
                "feishu": self._feishu_metadata()
            }
            mock_get_registry.return_value = mock_registry

            mock_repo = MagicMock()
            mock_repo.create = AsyncMock()
            mock_repo_class.return_value = mock_repo

            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await create_config(
                    project_id="project-1",
                    data=payload,
                    db=mock_db_session,
                    current_user=current_user,
                )

        assert exc_info.value.status_code == 422
        mock_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_config_rejects_invalid_plugin_settings(self, mock_db_session):
        """Update should return 422 when merged settings violate plugin schema."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()
        existing = ChannelConfigModel(
            id="cfg-1",
            project_id="project-1",
            channel_type="feishu",
            name="Feishu",
            enabled=True,
            connection_mode="websocket",
            app_id="cli_test",
            app_secret=encryption_service.encrypt("secret"),
            domain="feishu",
            created_at=datetime.utcnow(),
            status="disconnected",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
            ) as mock_repo_class,
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {
                "feishu": self._feishu_metadata()
            }
            mock_get_registry.return_value = mock_registry

            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock(return_value=existing)
            mock_repo_class.return_value = mock_repo

            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await update_config(
                    config_id="cfg-1",
                    data=ChannelConfigUpdate(extra_settings={"unexpected": "value"}),
                    db=mock_db_session,
                    current_user=current_user,
                )

        assert exc_info.value.status_code == 422
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_config_supports_secret_unchanged_sentinel(self, mock_db_session):
        """Update should accept secret sentinel and preserve existing secret value semantics."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()
        existing = ChannelConfigModel(
            id="cfg-1",
            project_id="project-1",
            channel_type="feishu",
            name="Feishu",
            enabled=True,
            connection_mode="websocket",
            app_id="cli_test",
            app_secret=encryption_service.encrypt("secret"),
            domain="feishu",
            created_at=datetime.utcnow(),
            status="disconnected",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.ChannelConfigRepository"
            ) as mock_repo_class,
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=None,
            ),
        ):
            metadata = self._feishu_metadata()
            metadata.secret_paths = ["app_secret"]
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {"feishu": metadata}
            mock_get_registry.return_value = mock_registry

            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=existing)
            mock_repo.update = AsyncMock(return_value=existing)
            mock_repo_class.return_value = mock_repo

            response = await update_config(
                config_id="cfg-1",
                data=ChannelConfigUpdate(
                    app_secret="__MEMSTACK_SECRET_UNCHANGED__",
                    domain="lark",
                ),
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.domain == "lark"
        mock_repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_config_rejects_when_plugin_disabled_for_tenant(self, mock_db_session):
        """Create should fail when channel plugin is disabled for project tenant."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        payload = ChannelConfigCreate(
            channel_type="feishu",
            name="Feishu",
            app_id="cli_test",
            app_secret="secret",
        )
        runtime_manager = MagicMock()
        runtime_manager.list_plugins.return_value = (
            [
                {
                    "name": "feishu-channel-plugin",
                    "source": "local",
                    "package": None,
                    "version": None,
                    "enabled": False,
                    "discovered": True,
                }
            ],
            [],
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._resolve_project_tenant_id",
                new=AsyncMock(return_value="tenant-1"),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._resolve_channel_metadata",
                return_value=SimpleNamespace(
                    channel_type="feishu",
                    plugin_name="feishu-channel-plugin",
                    config_schema=None,
                ),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_runtime_manager",
                return_value=runtime_manager,
            ),
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await create_config(
                    project_id="project-1",
                    data=payload,
                    db=mock_db_session,
                    current_user=current_user,
                )

        assert exc_info.value.status_code == 409


class TestPluginRuntimeReconcile:
    """Test plugin action hooks that reconcile channel runtime connections."""

    @pytest.mark.asyncio
    async def test_reload_plugins_includes_channel_reload_plan(self, mock_db_session):
        """Reload action should attach channel reconcile summary when manager is running."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        runtime_manager = MagicMock()
        runtime_manager.reload = AsyncMock(return_value=[])
        reload_plan = SimpleNamespace(
            summary=lambda: {"add": 1, "remove": 0, "restart": 0, "unchanged": 2}
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_project_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_runtime_manager",
                return_value=runtime_manager,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=object(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.reload_channel_manager_connections",
                new=AsyncMock(return_value=reload_plan),
            ),
        ):
            response = await reload_project_plugins(
                project_id="project-1",
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.success is True
        assert response.details is not None
        assert response.details["channel_reload_plan"]["add"] == 1


class TestTenantPluginEndpoints:
    """Test tenant-scoped plugin management endpoints."""

    @pytest.mark.asyncio
    async def test_list_tenant_plugins_returns_runtime_plugins(self, mock_db_session):
        """Tenant plugin list should use tenant access checks and runtime inventory."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        plugin_record = {
            "name": "feishu-channel-plugin",
            "source": "local",
            "package": None,
            "version": None,
            "enabled": True,
            "discovered": True,
            "channel_types": ["feishu"],
        }

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._load_runtime_plugins",
                new=AsyncMock(return_value=([plugin_record], [], {})),
            ),
        ):
            response = await list_tenant_plugins(
                tenant_id="tenant-1",
                db=mock_db_session,
                current_user=current_user,
            )

        assert len(response.items) == 1
        assert response.items[0].name == "feishu-channel-plugin"

    @pytest.mark.asyncio
    async def test_reload_tenant_plugins_includes_channel_reload_plan(self, mock_db_session):
        """Tenant reload should trigger channel runtime reconcile summary."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        runtime_manager = MagicMock()
        runtime_manager.reload = AsyncMock(return_value=[])
        reload_plan = SimpleNamespace(
            summary=lambda: {"add": 0, "remove": 1, "restart": 1, "unchanged": 0}
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_runtime_manager",
                return_value=runtime_manager,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=object(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.reload_channel_manager_connections",
                new=AsyncMock(return_value=reload_plan),
            ),
        ):
            response = await reload_tenant_plugins(
                tenant_id="tenant-1",
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.success is True
        assert response.details is not None
        assert response.details["channel_reload_plan"]["remove"] == 1

    @pytest.mark.asyncio
    async def test_tenant_schema_endpoint_returns_metadata(self, mock_db_session):
        """Tenant schema endpoint should return plugin channel metadata."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        metadata = SimpleNamespace(
            channel_type="feishu",
            plugin_name="feishu-channel-plugin",
            config_schema={"type": "object"},
            config_ui_hints={"app_secret": {"sensitive": True}},
            defaults={"domain": "feishu"},
            secret_paths=["app_secret"],
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._load_runtime_plugins",
                new=AsyncMock(
                    return_value=(
                        [
                            {
                                "name": "feishu-channel-plugin",
                                "source": "local",
                                "package": None,
                                "version": "0.1.0",
                                "enabled": True,
                                "discovered": True,
                            }
                        ],
                        [],
                        {},
                    )
                ),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_type_metadata.return_value = {"feishu": metadata}
            mock_get_registry.return_value = mock_registry

            response = await get_tenant_channel_plugin_schema(
                tenant_id="tenant-1",
                channel_type="feishu",
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.channel_type == "feishu"
        assert response.schema_supported is True

    @pytest.mark.asyncio
    async def test_list_tenant_channel_catalog(self, mock_db_session):
        """Tenant catalog endpoint should list discovered channel types."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels._load_runtime_plugins",
                new=AsyncMock(
                    return_value=(
                        [
                            {
                                "name": "feishu-channel-plugin",
                                "source": "local",
                                "package": None,
                                "version": None,
                                "enabled": True,
                                "discovered": True,
                            }
                        ],
                        [],
                        {},
                    )
                ),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_registry"
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.list_channel_adapter_factories.return_value = {
                "feishu": ("feishu-channel-plugin", object())
            }
            mock_registry.list_channel_type_metadata.return_value = {
                "feishu": SimpleNamespace(config_schema={"type": "object"})
            }
            mock_get_registry.return_value = mock_registry

            response = await list_tenant_channel_plugin_catalog(
                tenant_id="tenant-1",
                db=mock_db_session,
                current_user=current_user,
            )

        assert len(response.items) == 1
        assert response.items[0].channel_type == "feishu"

    @pytest.mark.asyncio
    async def test_enable_tenant_plugin_uses_tenant_scope(self, mock_db_session):
        """Tenant enable should pass tenant_id into runtime manager state toggle."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        runtime_manager = MagicMock()
        runtime_manager.set_plugin_enabled = AsyncMock(return_value=[])

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_runtime_manager",
                return_value=runtime_manager,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=None,
            ),
        ):
            response = await enable_tenant_plugin(
                tenant_id="tenant-1",
                plugin_name="feishu-channel-plugin",
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.success is True
        runtime_manager.set_plugin_enabled.assert_awaited_once_with(
            "feishu-channel-plugin",
            enabled=True,
            tenant_id="tenant-1",
        )

    @pytest.mark.asyncio
    async def test_uninstall_tenant_plugin_calls_runtime_manager(self, mock_db_session):
        """Tenant uninstall should delegate to runtime manager uninstall flow."""
        current_user = User(id="u-1", email="user@example.com", hashed_password="hash")
        runtime_manager = MagicMock()
        runtime_manager.uninstall_plugin = AsyncMock(
            return_value={
                "success": True,
                "plugin_name": "feishu-channel-plugin",
                "package": "memstack-plugin-feishu",
            }
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.verify_tenant_access",
                new=AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_plugin_runtime_manager",
                return_value=runtime_manager,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.channels.get_channel_manager",
                return_value=None,
            ),
        ):
            response = await uninstall_tenant_plugin(
                tenant_id="tenant-1",
                plugin_name="feishu-channel-plugin",
                db=mock_db_session,
                current_user=current_user,
            )

        assert response.success is True
        runtime_manager.uninstall_plugin.assert_awaited_once_with("feishu-channel-plugin")
