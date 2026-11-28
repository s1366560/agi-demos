"""Check immutable publisher bytes against live platform revocations and scan results."""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


async def check_catalog_release(
    db: AsyncSession, plugin: str, version: str, archive: bytes
) -> None:
    governance = (
        await db.execute(
            select(
                PlatformPluginPackageModel.revoked,
                PlatformPluginPackageModel.security_scan_status,
                PlatformPluginPackageModel.artifact_digest,
            )
            .where(
                PlatformPluginPackageModel.plugin_id == plugin,
                PlatformPluginPackageModel.version == version,
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if governance is None:
        return
    if governance.revoked:
        raise OptionalBusinessError("revoked", "this package version has been revoked")
    if governance.security_scan_status == "failed":
        raise OptionalBusinessError("scan_failed", "this package version failed its security scan")
    if hashlib.sha256(archive).hexdigest() != governance.artifact_digest:
        raise OptionalBusinessError("conflict", "release bytes differ from the marketplace version")
