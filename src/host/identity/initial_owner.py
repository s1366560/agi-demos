"""Create the first non-superuser tenant and project owner inside a host transaction."""

import asyncio
from uuid import uuid4

from email_validator import validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)


async def create_initial_owner(
    db: AsyncSession, *, email: str, password: str, tenant_name: str, project_name: str
) -> tuple[str, str, str]:
    """Create the initial identity inside the caller's locked database transaction."""
    email = validate_email(email, check_deliverability=False).normalized
    tenant_name, project_name = tenant_name.strip(), project_name.strip()
    if not tenant_name or not project_name:
        raise ValueError("Tenant and project names are required")
    if not password or len(password.encode()) > 72:
        raise ValueError("Provide a nonempty password within bcrypt's 72-byte limit")
    password_hash = await asyncio.to_thread(AuthService.get_password_hash, password)
    user = User(id=str(uuid4()), email=email, hashed_password=password_hash, is_superuser=False)
    db.add(user)
    await db.flush()
    tenant_id, project_id = str(uuid4()), str(uuid4())
    db.add(Tenant(id=tenant_id, slug=tenant_id, name=tenant_name, owner_id=user.id))
    await db.flush()
    db.add(Project(id=project_id, name=project_name, tenant_id=tenant_id, owner_id=user.id))
    await db.flush()
    db.add_all(
        [
            UserTenant(id=str(uuid4()), user_id=user.id, tenant_id=tenant_id, role="owner"),
            UserProject(id=str(uuid4()), user_id=user.id, project_id=project_id, role="owner"),
        ]
    )
    await db.flush()
    return user.id, tenant_id, project_id
