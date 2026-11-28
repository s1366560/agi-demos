"""Tenant-owned quota and usage operations available to an authenticated billing operation."""

from dataclasses import dataclass
from typing import Protocol


class TenantUsageAccessDenied(Exception):
    """The caller cannot inspect tenant-wide usage."""


class TenantQuotaAccessDenied(Exception):
    """Only the current tenant owner can change entitlements."""


class TenantEntitlementsNotFound(Exception):
    """No tenant exists for these entitlements."""


@dataclass(frozen=True, kw_only=True)
class TenantQuota:
    id: str
    name: str
    plan: str
    storage_limit: int
    projects_limit: int | None
    users_limit: int | None


@dataclass(frozen=True, kw_only=True)
class TenantUsage:
    projects: int
    memories: int
    users: int
    storage: int


class TenantEntitlementPort(Protocol):
    async def read_quota(self) -> TenantQuota: ...

    async def authorize_quota_change(self) -> None: ...

    async def read_usage(self) -> TenantUsage: ...

    async def update_quota(self, *, plan: str, storage_limit: int) -> TenantQuota: ...
