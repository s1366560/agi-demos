"""Apply the deployment's signed package selection once, when creating an empty project."""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.host.identity.initial_owner import create_initial_owner
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    lock_and_check_standalone,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class InitialOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: str
    password: SecretStr
    tenant_name: str
    project_name: str


class PackageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")]
    permissions: frozenset[str]


async def bootstrap_empty_project(
    engine: "AsyncEngine", directory: Path, keys: tuple[str, ...]
) -> None:
    """Concurrent replicas either observe the whole initial installation or retry it."""
    async with engine.begin() as connection:
        await connection.run_sync(lock_and_check_standalone)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            if await db.scalar(select(User.id).limit(1)) is not None:
                return
            owner = InitialOwner.model_validate_json((directory / "owner.json").read_bytes())
            selection = json.loads((directory / "selection.json").read_bytes())
            if not isinstance(selection, list) or not selection:
                raise ValueError("The initial package selection must be a nonempty list")
            packages = [PackageSelection.model_validate(item) for item in selection]
            if len({p.plugin_id for p in packages}) != len(packages):
                raise ValueError("The initial package selection contains repeated identities")
            user, tenant, project = await create_initial_owner(
                db,
                email=owner.email,
                password=owner.password.get_secret_value(),
                tenant_name=owner.tenant_name,
                project_name=owner.project_name,
            )
            service = ProjectPluginInstallationService(
                db, ScopeBindingV2(tenant_id=tenant, project_id=project), keys, actor_id=user
            )
            for package in packages:
                path = directory / "archives" / (package.plugin_id + ".mspkg")
                with path.open("rb") as archive:
                    raw = archive.read(12 * 1024 * 1024 + 1)
                if len(raw) > 12 * 1024 * 1024:
                    raise ValueError(
                        f"Initial archive exceeds the upload limit: {package.plugin_id}"
                    )
                verified = await service.inspect(raw)
                if verified.plugin_id != package.plugin_id or verified.kind != "business":
                    raise ValueError(f"Unexpected initial package identity: {package.plugin_id}")
                if not verified.approved_permissions <= package.permissions:
                    raise ValueError(
                        f"Initial package needs additional approval: {package.plugin_id}"
                    )
                await service.record(raw, verified.approved_permissions, user)
                await service.mutate(package.plugin_id, "enable", expected_version=verified.version)
