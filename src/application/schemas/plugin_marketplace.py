"""Schemas for the platform plugin marketplace API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MarketplacePackageSignature(BaseModel):
    algorithm: str = Field(default="Ed25519")
    public_key_pem: str
    signature_base64: str


class MarketplacePackageProvenance(BaseModel):
    predicate_type: str
    builder_id: str
    subject_name: str


class MarketplacePackageRequest(BaseModel):
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
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
