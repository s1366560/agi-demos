"""Unit tests for tenant agent config router helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.model.agent.tenant_agent_config import (
    ConfigType,
    RuntimeHookConfig,
    TenantAgentConfig,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    has_global_admin_access,
    is_global_admin,
    require_tenant_access as _require_tenant_access,
)
from src.infrastructure.adapters.primary.web.routers.agent.config import (
    _validate_runtime_hooks,
    _validate_tool_policy,
    check_config_modify_permission,
    get_hook_catalog,
    get_tenant_agent_config,
    update_tenant_agent_config,
)
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    UpdateTenantAgentConfigRequest,
)


def _make_user(*, is_global_admin: bool = False) -> SimpleNamespace:
    """Create a minimal current_user stub for access checks."""
    roles = []
    if is_global_admin:
        roles.append(SimpleNamespace(tenant_id=None, role=SimpleNamespace(name="system_admin")))
    return SimpleNamespace(id="user-1", roles=roles, is_superuser=False)


@pytest.mark.unit
class TestAccessHelpers:
    def test_is_global_admin_ignores_is_superuser_flag_without_roles(self) -> None:
        assert is_global_admin(SimpleNamespace(id="user-1", is_superuser=True)) is False

    def test_is_global_admin_supports_preloaded_roles(self) -> None:
        user = SimpleNamespace(
            id="user-1",
            is_superuser=False,
            roles=[SimpleNamespace(tenant_id=None, role=SimpleNamespace(name="system_admin"))],
        )

        assert is_global_admin(user) is True

    def test_is_global_admin_ignores_tenant_scoped_admin_roles(self) -> None:
        user = SimpleNamespace(
            id="user-1",
            is_superuser=False,
            roles=[SimpleNamespace(tenant_id="tenant-1", role=SimpleNamespace(name="admin"))],
        )

        assert is_global_admin(user) is False

    def test_is_global_admin_does_not_touch_unloaded_nested_roles(self) -> None:
        class LazyUserRole:
            tenant_id = None

            @property
            def role(self) -> SimpleNamespace:
                raise AssertionError("should not touch unloaded role relationship")

        user = SimpleNamespace(id="user-1", is_superuser=False, roles=[LazyUserRole()])

        assert is_global_admin(user) is False

    @pytest.mark.asyncio
    async def test_has_global_admin_access_reads_persisted_system_admin_role(self) -> None:
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = "role-id"
        db.execute = AsyncMock(return_value=result)

        assert await has_global_admin_access(db, SimpleNamespace(id="user-1")) is True


@pytest.mark.unit
class TestRequireTenantAccess:
    """Tests for tenant access enforcement."""

    @pytest.mark.asyncio
    async def test_member_can_read_tenant_config(self) -> None:
        db = MagicMock()
        tenant_exists_result = MagicMock()
        tenant_exists_result.scalar_one_or_none.return_value = "tenant-1"
        global_role_result = MagicMock()
        global_role_result.scalar_one_or_none.return_value = None
        tenant_role_result = MagicMock()
        tenant_role_result.scalar_one_or_none.return_value = "member"
        db.execute = AsyncMock(
            side_effect=[tenant_exists_result, global_role_result, tenant_role_result]
        )

        await _require_tenant_access(db, _make_user(), "tenant-1")

    @pytest.mark.asyncio
    async def test_outsider_is_rejected(self) -> None:
        db = MagicMock()
        tenant_exists_result = MagicMock()
        tenant_exists_result.scalar_one_or_none.return_value = "tenant-1"
        global_role_result = MagicMock()
        global_role_result.scalar_one_or_none.return_value = None
        tenant_role_result = MagicMock()
        tenant_role_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(
            side_effect=[tenant_exists_result, global_role_result, tenant_role_result]
        )

        with pytest.raises(HTTPException, match="Tenant access required"):
            await _require_tenant_access(db, _make_user(), "tenant-1")

    @pytest.mark.asyncio
    async def test_non_admin_cannot_modify(self) -> None:
        db = MagicMock()
        tenant_exists_result = MagicMock()
        tenant_exists_result.scalar_one_or_none.return_value = "tenant-1"
        global_role_result = MagicMock()
        global_role_result.scalar_one_or_none.return_value = None
        tenant_role_result = MagicMock()
        tenant_role_result.scalar_one_or_none.return_value = "member"
        db.execute = AsyncMock(
            side_effect=[tenant_exists_result, global_role_result, tenant_role_result]
        )

        with pytest.raises(HTTPException, match="Admin access required"):
            await _require_tenant_access(db, _make_user(), "tenant-1", require_admin=True)

    @pytest.mark.asyncio
    async def test_global_admin_bypasses_membership_lookup(self) -> None:
        db = MagicMock()
        tenant_exists_result = MagicMock()
        tenant_exists_result.scalar_one_or_none.return_value = "tenant-1"
        db.execute = AsyncMock(return_value=tenant_exists_result)

        await _require_tenant_access(db, _make_user(is_global_admin=True), "tenant-1")

        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_tenant_returns_404(self) -> None:
        db = MagicMock()
        tenant_exists_result = MagicMock()
        tenant_exists_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=tenant_exists_result)

        with pytest.raises(HTTPException, match="Tenant not found") as exc_info:
            await _require_tenant_access(db, _make_user(), "missing-tenant")

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestValidateRuntimeHooks:
    """Tests for runtime hook override validation."""

    def test_accepts_valid_hook_override(self) -> None:
        _validate_runtime_hooks(
            [
                RuntimeHookConfig(
                    plugin_name="sisyphus-runtime",
                    hook_name="before_response",
                    enabled=True,
                    priority=30,
                    settings={
                        "response_reminder": "Keep going until the task is done.",
                        "require_direct_outcome": True,
                    },
                )
            ]
        )

    def test_rejects_invalid_hook_settings(self) -> None:
        with pytest.raises(HTTPException, match="Invalid settings"):
            _validate_runtime_hooks(
                [
                    RuntimeHookConfig(
                        plugin_name="sisyphus-runtime",
                        hook_name="before_response",
                        enabled=True,
                        settings={"unknown_setting": "nope"},
                    )
                ]
            )

    def test_rejects_oversized_hook_settings(self) -> None:
        with pytest.raises(HTTPException, match="cannot exceed"):
            _validate_runtime_hooks(
                [
                    RuntimeHookConfig(
                        plugin_name="sisyphus-runtime",
                        hook_name="before_response",
                        enabled=True,
                        settings={"response_reminder": "x" * 5000},
                    )
                ]
            )

    def test_allows_round_tripping_existing_unknown_hooks(self) -> None:
        legacy_hook = RuntimeHookConfig(
            plugin_name="legacy-plugin",
            hook_name="legacy-hook",
            enabled=True,
            priority=None,
            settings={"keep": True},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []

        with patch(
            "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
            return_value=registry,
        ):
            _validate_runtime_hooks(
                [legacy_hook],
                allowed_unknown_hook_keys={legacy_hook.key},
            )


@pytest.mark.unit
class TestValidateToolPolicy:
    def test_rejects_duplicate_enabled_tools(self) -> None:
        with pytest.raises(HTTPException, match="duplicate tool"):
            _validate_tool_policy(["bash", "bash"], [])

    def test_rejects_overlap_between_enabled_and_disabled(self) -> None:
        with pytest.raises(HTTPException, match="both enabled and disabled"):
            _validate_tool_policy(["bash"], ["bash"])

    def test_rejects_oversized_existing_unknown_hook_settings(self) -> None:
        legacy_hook = RuntimeHookConfig(
            plugin_name="legacy-plugin",
            hook_name="legacy-hook",
            enabled=True,
            priority=None,
            settings={"payload": "x" * 5000},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
                return_value=registry,
            ),
            pytest.raises(HTTPException, match="cannot exceed"),
        ):
            _validate_runtime_hooks(
                [legacy_hook],
                allowed_unknown_hook_keys={legacy_hook.key},
            )

    def test_rejects_custom_hook_without_hook_family(self) -> None:
        custom_hook = RuntimeHookConfig(
            hook_name="before_response",
            plugin_name="__custom__",
            executor_kind="script",
            source_ref="src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
            entrypoint="append_demo_response_instruction",
            enabled=True,
            settings={},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
                return_value=registry,
            ),
            pytest.raises(HTTPException, match="hook_family"),
        ):
            _validate_runtime_hooks([custom_hook])

    def test_allows_well_known_custom_hook_with_explicit_identity(self) -> None:
        custom_hook = RuntimeHookConfig(
            hook_name="before_response",
            plugin_name="__custom__",
            hook_family="mutating",
            executor_kind="script",
            source_ref="src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
            entrypoint="append_demo_response_instruction",
            enabled=True,
            settings={},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []
        registry.list_well_known_hooks.return_value = {"before_response"}

        with patch(
            "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
            return_value=registry,
        ):
            _validate_runtime_hooks([custom_hook])

    def test_rejects_script_executor_for_policy_family(self) -> None:
        custom_hook = RuntimeHookConfig(
            hook_name="before_tool_execution",
            plugin_name="__custom__",
            hook_family="policy",
            executor_kind="script",
            source_ref="src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
            entrypoint="append_demo_response_instruction",
            enabled=True,
            settings={},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []
        registry.list_well_known_hooks.return_value = {"before_tool_execution"}

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
                return_value=registry,
            ),
            pytest.raises(HTTPException, match="cannot use executor_kind"),
        ):
            _validate_runtime_hooks([custom_hook])

    def test_rejects_custom_hook_timeout_outside_bounds(self) -> None:
        custom_hook = RuntimeHookConfig(
            hook_name="before_response",
            plugin_name="__custom__",
            hook_family="mutating",
            executor_kind="script",
            source_ref="src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
            entrypoint="append_demo_response_instruction",
            enabled=True,
            settings={"timeout_seconds": 999},
        )
        registry = MagicMock()
        registry.list_hook_catalog.return_value = []
        registry.list_well_known_hooks.return_value = {"before_response"}

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
                return_value=registry,
            ),
            pytest.raises(HTTPException, match="timeout_seconds must be between"),
        ):
            _validate_runtime_hooks([custom_hook])


@pytest.mark.unit
class TestUpdateTenantAgentConfig:
    @pytest.mark.asyncio
    async def test_first_save_returns_custom_config_type(self) -> None:
        repo = MagicMock()
        repo.get_by_tenant = AsyncMock(return_value=None)
        repo.save = AsyncMock(side_effect=lambda config: config)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=repo,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ),
        ):
            response = await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(llm_model="openai/gpt-5.4"),
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert response.config_type == "custom"

    @pytest.mark.asyncio
    async def test_unrelated_update_does_not_revalidate_existing_runtime_hooks(self) -> None:
        repo = MagicMock()
        repo.get_by_tenant = AsyncMock(
            return_value=TenantAgentConfig(
                id="cfg-1",
                tenant_id="tenant-1",
                config_type=ConfigType.CUSTOM,
                llm_model="openai/gpt-5.4",
                llm_temperature=0.2,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=8,
                tool_timeout_seconds=45,
                enabled_tools=[],
                disabled_tools=[],
                runtime_hooks=[
                    RuntimeHookConfig(
                        plugin_name="sisyphus-runtime",
                        hook_name="before_response",
                        enabled=True,
                        settings={"legacy_setting": "stale"},
                    )
                ],
            )
        )
        repo.save = AsyncMock(side_effect=lambda config: config)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=repo,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config._validate_runtime_hooks"
            ) as validate_runtime_hooks,
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ),
        ):
            response = await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(llm_model="anthropic/claude-sonnet-4.5"),
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        validate_runtime_hooks.assert_not_called()
        assert response.llm_model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_non_tool_update_still_validates_final_tool_policy(self) -> None:
        repo = MagicMock()
        repo.get_by_tenant = AsyncMock(
            return_value=TenantAgentConfig(
                id="cfg-1",
                tenant_id="tenant-1",
                config_type=ConfigType.CUSTOM,
                llm_model="openai/gpt-5.4",
                llm_temperature=0.2,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=8,
                tool_timeout_seconds=45,
                enabled_tools=["bash"],
                disabled_tools=["bash"],
                runtime_hooks=[],
            )
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=repo,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ),
            pytest.raises(HTTPException, match="both enabled and disabled") as exc_info,
        ):
            await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(llm_model="anthropic/claude-sonnet-4.5"),
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert exc_info.value.status_code == 422


@pytest.mark.unit
class TestGetTenantAgentConfig:
    @pytest.mark.asyncio
    async def test_non_admin_redacts_runtime_hook_settings(self) -> None:
        repo = MagicMock()
        repo.get_by_tenant = AsyncMock(
            return_value=TenantAgentConfig(
                id="cfg-1",
                tenant_id="tenant-1",
                config_type=ConfigType.CUSTOM,
                llm_model="openai/gpt-5.4",
                llm_temperature=0.2,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=8,
                tool_timeout_seconds=45,
                enabled_tools=[],
                disabled_tools=[],
                runtime_hooks=[
                    RuntimeHookConfig(
                        plugin_name="sisyphus-runtime",
                        hook_name="before_response",
                        enabled=True,
                        settings={"response_reminder": "keep going"},
                    )
                ],
            )
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.has_tenant_admin_access",
                AsyncMock(return_value=False),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=repo,
            ),
        ):
            response = await get_tenant_agent_config(
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert response.runtime_hook_settings_redacted is True
        assert response.runtime_hooks[0].settings == {}

    @pytest.mark.asyncio
    async def test_admin_keeps_runtime_hook_settings_visible(self) -> None:
        repo = MagicMock()
        repo.get_by_tenant = AsyncMock(
            return_value=TenantAgentConfig(
                id="cfg-1",
                tenant_id="tenant-1",
                config_type=ConfigType.CUSTOM,
                llm_model="openai/gpt-5.4",
                llm_temperature=0.2,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=8,
                tool_timeout_seconds=45,
                enabled_tools=[],
                disabled_tools=[],
                runtime_hooks=[
                    RuntimeHookConfig(
                        plugin_name="sisyphus-runtime",
                        hook_name="before_response",
                        enabled=True,
                        settings={"response_reminder": "keep going"},
                    )
                ],
            )
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.has_tenant_admin_access",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=repo,
            ),
        ):
            response = await get_tenant_agent_config(
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert response.runtime_hook_settings_redacted is False
        assert response.runtime_hooks[0].settings == {"response_reminder": "keep going"}


@pytest.mark.unit
class TestHookCatalogAccess:
    @pytest.mark.asyncio
    async def test_hook_catalog_requires_admin_access(self) -> None:
        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="Admin access required")
                ),
            ),
            pytest.raises(HTTPException, match="Admin access required") as exc_info,
        ):
            await get_hook_catalog(
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_hook_catalog_includes_family_and_executor_defaults(self) -> None:
        registry = MagicMock()
        registry.list_hook_catalog.return_value = [
            SimpleNamespace(
                plugin_name="sisyphus-runtime",
                hook_name="before_response",
                hook_family="mutating",
                display_name="Before response",
                description="desc",
                default_priority=30,
                default_enabled=True,
                default_executor_kind="builtin",
                default_source_ref="sisyphus-runtime",
                default_entrypoint=None,
                default_settings={},
                settings_schema={},
            ),
            SimpleNamespace(
                plugin_name="memory-runtime",
                hook_name="before_prompt_build",
                hook_family="mutating",
                display_name="Memory recall",
                description="desc",
                default_priority=25,
                default_enabled=True,
                default_executor_kind="builtin",
                default_source_ref="memory-runtime",
                default_entrypoint=None,
                default_settings={},
                settings_schema={},
            ),
        ]

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.get_plugin_registry",
                return_value=registry,
            ),
        ):
            response = await get_hook_catalog(
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert response.hooks[0].hook_family == "mutating"
        assert response.hooks[0].default_executor_kind == "builtin"
        assert {hook.plugin_name for hook in response.hooks} == {
            "sisyphus-runtime",
            "memory-runtime",
        }


@pytest.mark.unit
class TestCheckConfigModifyPermission:
    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self) -> None:
        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(side_effect=RuntimeError("db unavailable")),
            ),
            pytest.raises(HTTPException, match="Internal server error") as exc_info,
        ):
            await check_config_modify_permission(
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_server_http_exception_is_not_masked(self) -> None:
        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(side_effect=HTTPException(status_code=500, detail="boom")),
            ),
            pytest.raises(HTTPException, match="boom") as exc_info,
        ):
            await check_config_modify_permission(
                tenant_id="tenant-1",
                current_user=_make_user(),
                db=MagicMock(),
            )

        assert exc_info.value.status_code == 500
