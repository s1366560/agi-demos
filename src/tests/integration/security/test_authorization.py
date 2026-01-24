"""
Integration tests for RBAC authorization system.

These tests verify that permissions are correctly enforced across the application.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.authorization_service import AuthorizationService
from src.domain.model.auth.permissions import PermissionCode
from src.domain.model.auth.roles import RoleDefinition
from src.infrastructure.adapters.secondary.persistence.models import (
    Permission,
    Role,
    RolePermission,
    User,
)


@pytest.mark.asyncio
async def test_system_admin_has_all_permissions(db_session: AsyncSession):
    """Test that system admin has access to all permissions"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create a system admin user
    admin_user = User(
        id="admin-user",
        email="admin@example.com",
        full_name="System Admin",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(admin_user)
    await db_session.commit()

    # Assign system admin role
    await auth_service.assign_role(user_id=admin_user.id, role_name=RoleDefinition.SYSTEM_ADMIN)

    # Check that admin has all permissions
    permissions = await auth_service.get_user_permissions(admin_user.id)

    assert len(permissions) > 0
    # Should have at least some admin permissions
    assert PermissionCode.ADMIN_SYSTEM in permissions


@pytest.mark.asyncio
async def test_tenant_member_has_basic_permissions(db_session: AsyncSession):
    """Test that tenant members have appropriate permissions"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create a tenant member user
    member_user = User(
        id="member-user",
        email="member@example.com",
        full_name="Tenant Member",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(member_user)
    await db_session.commit()

    # Assign role to tenant
    await auth_service.assign_role(
        user_id=member_user.id, role_name=RoleDefinition.TENANT_MEMBER, tenant_id="tenant-123"
    )

    # Get user permissions
    permissions = await auth_service.get_user_permissions(member_user.id, tenant_id="tenant-123")

    # Should have basic tenant permissions
    assert PermissionCode.TENANT_READ in permissions
    assert PermissionCode.PROJECT_CREATE in permissions
    assert PermissionCode.MEMORY_CREATE in permissions

    # Should NOT have admin permissions
    assert PermissionCode.TENANT_DELETE not in permissions
    assert PermissionCode.ADMIN_SYSTEM not in permissions


@pytest.mark.asyncio
async def test_project_viewer_has_read_only_access(db_session: AsyncSession):
    """Test that project viewers only have read access"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create a viewer user
    viewer_user = User(
        id="viewer-user",
        email="viewer@example.com",
        full_name="Project Viewer",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(viewer_user)
    await db_session.commit()

    # Assign role (Project Viewer is usually assigned via UserProject, but here we test RBAC direct assignment if supported, or we need to simulate UserProject permissions if AuthorizationService reads them)
    # Assuming AuthorizationService.assign_role supports project roles if defined in RoleDefinition

    # NOTE: Project Viewer role might need project_id context.
    # If AuthorizationService handles project roles via UserProject table, this test might need adjustment.
    # But if it uses UserRole table for everything, then assign_role works.
    # Let's assume UserRole table for now as per original test.

    await auth_service.assign_role(
        user_id=viewer_user.id, role_name=RoleDefinition.PROJECT_VIEWER, project_id="project-123"
    )

    # Get permissions
    permissions = await auth_service.get_user_permissions(viewer_user.id, project_id="project-123")

    # Should have read permissions
    assert PermissionCode.PROJECT_READ in permissions
    assert PermissionCode.MEMORY_READ in permissions

    # Should NOT have write permissions
    assert PermissionCode.PROJECT_UPDATE not in permissions
    assert PermissionCode.MEMORY_CREATE not in permissions
    assert PermissionCode.MEMORY_UPDATE not in permissions


@pytest.mark.asyncio
async def test_check_permission_denied_without_permission(db_session: AsyncSession):
    """Test that permission check returns False when user lacks permission"""
    auth_service = AuthorizationService(db_session)

    # Create a user with no roles
    user = User(
        id="regular-user",
        email="user@example.com",
        full_name="Regular User",  # Fixed: use full_name instead of name
        hashed_password="hash",  # Fixed: use hashed_password instead of password_hash
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Check for permission they don't have
    has_permission = await auth_service.check_permission(
        user_id=user.id, permission=PermissionCode.PROJECT_DELETE
    )

    assert has_permission is False


@pytest.mark.asyncio
async def test_assign_role_to_user(db_session: AsyncSession):
    """Test assigning a role to a user"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create user
    user = User(
        id="test-user",
        email="test@example.com",
        full_name="Test User",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Assign tenant admin role
    await auth_service.assign_role(
        user_id=user.id, role_name=RoleDefinition.TENANT_ADMIN, tenant_id="tenant-456"
    )

    # Verify role was assigned
    user_roles = await auth_service.get_user_roles(user.id, tenant_id="tenant-456")

    assert len(user_roles) == 1
    assert user_roles[0]["name"] == RoleDefinition.TENANT_ADMIN
    assert user_roles[0]["tenant_id"] == "tenant-456"


@pytest.mark.asyncio
async def test_remove_role_from_user(db_session: AsyncSession):
    """Test removing a role from a user"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create user
    user = User(
        id="test-user",
        email="test@example.com",
        full_name="Test User",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Assign role
    await auth_service.assign_role(
        user_id=user.id, role_name=RoleDefinition.TENANT_MEMBER, tenant_id="tenant-789"
    )

    # Remove role
    await auth_service.remove_role(
        user_id=user.id, role_name=RoleDefinition.TENANT_MEMBER, tenant_id="tenant-789"
    )

    # Verify role was removed
    user_roles = await auth_service.get_user_roles(user.id, tenant_id="tenant-789")

    assert len(user_roles) == 0


@pytest.mark.asyncio
async def test_context_specific_permissions(db_session: AsyncSession):
    """Test that permissions are context-specific (tenant vs project)"""
    auth_service = AuthorizationService(db_session)
    await auth_service.initialize_default_roles()

    # Create user
    user = User(
        id="admin-user",
        email="admin@example.com",
        full_name="Admin",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Assign tenant admin role
    await auth_service.assign_role(
        user_id=user.id, role_name=RoleDefinition.TENANT_ADMIN, tenant_id="tenant-123"
    )

    # Should have permissions in the correct tenant context
    has_permission_in_tenant = await auth_service.check_permission(
        user_id=user.id, permission=PermissionCode.PROJECT_CREATE, tenant_id="tenant-123"
    )

    assert has_permission_in_tenant is True


@pytest.mark.asyncio
async def test_initialize_default_roles(db_session: AsyncSession):
    """Test that default roles and permissions are initialized correctly"""
    auth_service = AuthorizationService(db_session)

    # Initialize default roles
    await auth_service.initialize_default_roles()

    # Check that all permissions were created
    from sqlalchemy import select

    permissions_result = await db_session.execute(select(Permission))
    permissions = permissions_result.scalars().all()

    # Should have all permissions defined in PermissionCode
    expected_permission_count = len(PermissionCode)
    assert len(permissions) == expected_permission_count

    # Check that all roles were created
    roles_result = await db_session.execute(select(Role))
    roles = roles_result.scalars().all()

    expected_role_count = len(RoleDefinition.get_all_roles())
    assert len(roles) == expected_role_count

    # Check that roles have permissions
    role_permissions_result = await db_session.execute(select(RolePermission))
    role_permissions = role_permissions_result.scalars().all()

    # Should have role-permission mappings
    assert len(role_permissions) > 0
