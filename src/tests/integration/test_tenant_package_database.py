"""Two API writers compete for one tenant revision in a disposable PostgreSQL database."""

import asyncio
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from plugins.business.billing.build import ROOT, build_release
from src.host.packages.tenant_installation import TenantPackageService
from src.infrastructure.adapters.secondary.persistence.models import Project, Tenant, User
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    initialize_package_kernel_database,
)
from src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation import (
    TenantPluginRelease,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError
from src.tests.integration.test_package_kernel_database import (  # noqa: F401
    database as _database,
    pytestmark,
)

database = _database


async def test_first_selection_locks_tenant_without_a_project(database):
    await initialize_package_kernel_database(database)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions.begin() as db:
        db.add(User(id="owner", email="tenant@example.test", hashed_password="unused"))
        await db.flush()
        db.add(Tenant(id="tenant", name="Tenant", slug="tenant", owner_id="owner"))
    key = Ed25519PrivateKey.generate()
    keys = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )

    async def install(version):
        raw = build_release(
            json.loads((ROOT / "plans.json").read_text()), version=version, signer=key
        )
        async with sessions() as db:
            ops = TenantPackageService(db, "tenant", keys, "owner")
            pkg = await ops.inspect(raw)
            await ops.lock()
            return await ops.record(
                raw,
                pkg.approved_permissions,
                0,
                pkg.digest,
                identity=(pkg.plugin_id, pkg.version),
                activate=True,
            )

    results = await asyncio.gather(install("1.2.0"), install("1.2.1"), return_exceptions=True)
    assert (
        sum(
            isinstance(result, OptionalBusinessError) and result.code == "conflict"
            for result in results
        )
        == 1
    )
    async with sessions() as db:
        packages = TenantPackageService(db, "tenant", keys, "owner")
        active = await packages.projection("memstack-billing")
        assert active["desired_revision"] == 1 and active["running_version"] in {"1.2.0", "1.2.1"}
        assert await db.scalar(select(func.count()).select_from(Project)) == 0
        assert await db.scalar(select(func.count()).select_from(TenantPluginRelease)) == 1
