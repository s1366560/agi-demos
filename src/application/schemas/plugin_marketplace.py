"""Schemas for the platform plugin marketplace API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MarketplacePackageSignature(BaseModel):
    algorithm: str = Field(default="Ed25519")
    public_key_pem: str
    signature_base64: str


class MarketplacePackageProvenance(BaseModel):
    predicate_type: str
    builder_id: str
    subject_name: str


class MarketplaceArtifactSource(BaseModel):
    registry: str = Field(min_length=1, max_length=512)
    repository: str = Field(min_length=1, max_length=255)
    manifest_sha256: str = Field(min_length=64, max_length=64)


class MarketplacePackageRequest(BaseModel):
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    artifact: MarketplaceArtifactSource
    artifact_sha256: str = Field(min_length=64, max_length=64)
    manifest: dict[str, object]
    signature: MarketplacePackageSignature
    provenance: MarketplacePackageProvenance
    approved_permissions: frozenset[str] = Field(default_factory=frozenset)
    tenant_admin_approved: bool = False
    security_scan_passed: bool = False


class MarketplacePackageResponse(BaseModel):
    plugin_id: str
    version: str
    status: str
    reason: str


class MarketplacePackageCatalogEntry(BaseModel):
    plugin_id: str
    version: str
    publisher: str
    artifact_digest: str
    artifact_registry: str
    artifact_repository: str
    oci_manifest_digest: str
    install_status: str
    manifest: dict[str, object]
    signature: dict[str, object]
    provenance: dict[str, object]
    security_scan_status: str
    revoked: bool
    revocation_reason: str | None = None


class MarketplacePackageDetailResponse(BaseModel):
    plugin_id: str
    versions: list[MarketplacePackageCatalogEntry]


class MarketplacePackageApprovalRequest(BaseModel):
    version: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    approved_permissions: frozenset[str] = Field(default_factory=frozenset)


class MarketplacePackageApprovalResponse(BaseModel):
    plugin_id: str
    version: str
    status: Literal["approved", "revoked"]
    granted_permissions: list[str] = Field(default_factory=list)


class MarketplacePackageRevocationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2048)
    version: str | None = Field(default=None, min_length=1)


class MarketplacePackageRevocationResponse(BaseModel):
    plugin_id: str
    revoked_versions: list[str]
    revoked_permissions: int


class MarketplacePackageUninstallRequest(BaseModel):
    version: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class MarketplacePackageUninstallResponse(BaseModel):
    plugin_id: str
    version: str
    status: Literal["uninstalled"]
    desired_removed: bool
    revoked_permissions: int
