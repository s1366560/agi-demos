"""Plugin trust gate, package verification, and resource quota enforcement."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.domain.model.plugins import PluginManifest, PluginRuntimeKind, PluginTrust
from src.domain.ports.plugins import (
    RUNTIME_PERMISSIONS,
    PluginPermission,
    PluginTrustDecision,
    ResourceQuota,
)


class PluginTrustGateError(RuntimeError):
    """Raised when a plugin or package cannot be activated."""


class PluginTrustGate:
    """Deterministically gate runtime and requested permissions."""

    def decide(
        self,
        manifest: PluginManifest,
        approved_permissions: frozenset[PluginPermission],
    ) -> PluginTrustDecision:
        """Return the effective permission set or a denial reason."""
        allowed = RUNTIME_PERMISSIONS[manifest.runtime]
        requested: set[PluginPermission] = set()
        for capability in manifest.provides:
            for permission in capability.permissions:
                try:
                    requested.add(PluginPermission(permission))
                except ValueError:
                    return self._deny(manifest, f"unknown permission: {permission}", frozenset())

        if (
            manifest.trust == PluginTrust.UNTRUSTED
            and manifest.runtime == PluginRuntimeKind.PYTHON_TRUSTED
        ):
            return self._deny(
                manifest, "untrusted plugin cannot use python-trusted runtime", frozenset()
            )
        if not requested.issubset(allowed):
            return self._deny(
                manifest,
                f"runtime {manifest.runtime.value} cannot request "
                f"{','.join(sorted(item.value for item in requested - allowed))}",
                frozenset(),
            )
        if not approved_permissions.issubset(allowed) or not approved_permissions.issubset(
            requested
        ):
            return self._deny(
                manifest,
                "approved permissions must be a subset of runtime and requested permissions",
                frozenset(),
            )
        return PluginTrustDecision(
            allowed=True,
            plugin_id=manifest.id,
            trust=manifest.trust,
            runtime=manifest.runtime,
            granted_permissions=frozenset(approved_permissions),
            reason="granted",
        )

    @staticmethod
    def _deny(
        manifest: PluginManifest,
        reason: str,
        granted: frozenset[PluginPermission],
    ) -> PluginTrustDecision:
        return PluginTrustDecision(
            allowed=False,
            plugin_id=manifest.id,
            trust=manifest.trust,
            runtime=manifest.runtime,
            granted_permissions=granted,
            reason=reason,
        )


@dataclass(frozen=True)
class PluginPackageBundle:
    """Verified inputs for one plugin package."""

    manifest: PluginManifest
    canonical_manifest: str
    artifact_digest: str
    signature_base64: str
    public_key_pem: str
    provenance: Mapping[str, Any]
    checksum: Mapping[str, str]


@dataclass(frozen=True)
class MarketplaceCatalogEntry:
    """One immutable package catalog row."""

    plugin_id: str
    version: str
    publisher: str
    bundle: PluginPackageBundle
    revoked: bool = False
    revocation_reason: str | None = None


class PluginPackageVerifier:
    """Verify Ed25519 package signatures and SLSA-style provenance."""

    def __init__(
        self,
        trusted_public_keys: tuple[str, ...],
        *,
        revoked_publisher_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._trusted_keys = tuple(_load_ed25519_public_key(key) for key in trusted_public_keys)
        self._revoked = set(revoked_publisher_keys)

    def verify(
        self,
        entry: MarketplaceCatalogEntry,
        *,
        artifact_sha256: str,
    ) -> None:
        """Raise before installation when package trust or provenance fails."""
        if entry.revoked:
            raise PluginTrustGateError(f"package revoked: {entry.revocation_reason or 'unknown'}")
        if entry.plugin_id != entry.bundle.manifest.id:
            raise PluginTrustGateError("catalog plugin id does not match manifest")
        if entry.version != entry.bundle.manifest.version:
            raise PluginTrustGateError("catalog plugin version does not match manifest")
        if entry.bundle.canonical_manifest != entry.bundle.manifest.to_json():
            raise PluginTrustGateError("canonical manifest bytes do not match manifest")
        if entry.bundle.public_key_pem in self._revoked:
            raise PluginTrustGateError("publisher key is revoked")
        if entry.bundle.artifact_digest != artifact_sha256:
            raise PluginTrustGateError("artifact digest mismatch")

        expected_checksum = entry.bundle.checksum.get("sha256")
        if expected_checksum != artifact_sha256:
            raise PluginTrustGateError("checksum manifest does not match artifact")

        signed_payload = _package_signature_payload(entry.bundle)
        try:
            signature = base64.b64decode(entry.bundle.signature_base64, validate=True)
            public_key = serialization.load_pem_public_key(entry.bundle.public_key_pem.encode())
        except (ValueError, TypeError) as exc:
            raise PluginTrustGateError(f"invalid package signature encoding: {exc}") from exc
        if not isinstance(public_key, Ed25519PublicKey):
            raise PluginTrustGateError("package signature must use Ed25519")
        try:
            public_key.verify(signature, signed_payload)
        except InvalidSignature as exc:
            raise PluginTrustGateError("package signature verification failed") from exc

        if not any(_same_ed25519_key(public_key, trusted) for trusted in self._trusted_keys):
            raise PluginTrustGateError("package publisher key is not trusted")
        self._verify_provenance(entry)

    @staticmethod
    def _verify_provenance(entry: MarketplaceCatalogEntry) -> None:
        provenance = entry.bundle.provenance
        if not isinstance(provenance, dict):
            raise PluginTrustGateError("provenance must be an object")
        predicate = provenance.get("predicateType")
        if predicate != "https://slsa.dev/provenance/v1":
            raise PluginTrustGateError("unsupported provenance predicate")
        subject = provenance.get("subject")
        if not isinstance(subject, list) or not subject:
            raise PluginTrustGateError("provenance subject is required")
        subject_digest = subject[0].get("digest", {}) if isinstance(subject[0], dict) else {}
        if (
            not isinstance(subject_digest, dict)
            or subject_digest.get("sha256") != entry.bundle.artifact_digest
        ):
            raise PluginTrustGateError("provenance subject digest does not match artifact")
        builder = provenance.get("builder", {})
        if not isinstance(builder, dict) or not builder.get("id"):
            raise PluginTrustGateError("provenance builder is required")


class ResourceQuotaEnforcer:
    """Per-plugin quota accounting with structured exhaustion errors."""

    def __init__(self, quotas: Mapping[str, ResourceQuota]) -> None:
        self._quotas = {plugin_id: quota for plugin_id, quota in quotas.items()}
        self._concurrent: dict[str, int] = {}
        self._window_started: dict[str, float] = {}
        self._window_requests: dict[str, int] = {}

    def acquire(self, plugin_id: str, *, output_bytes: int = 0) -> None:
        """Reserve one invocation and output budget atomically."""
        quota = self._quotas.get(plugin_id)
        if quota is None:
            return
        current = self._concurrent.get(plugin_id, 0)
        if quota.max_concurrent_calls is not None and current >= quota.max_concurrent_calls:
            raise PluginQuotaExceededError(plugin_id, "max_concurrent_calls")
        if quota.max_output_bytes is not None and output_bytes > quota.max_output_bytes:
            raise PluginQuotaExceededError(plugin_id, "max_output_bytes")
        now = time.monotonic()
        if now - self._window_started.get(plugin_id, now) >= 60:
            self._window_started[plugin_id] = now
            self._window_requests[plugin_id] = 0
        requests = self._window_requests.get(plugin_id, 0)
        if (
            quota.max_network_requests_per_minute is not None
            and requests >= quota.max_network_requests_per_minute
        ):
            raise PluginQuotaExceededError(plugin_id, "max_network_requests_per_minute")
        self._concurrent[plugin_id] = current + 1
        self._window_requests[plugin_id] = requests + 1

    def release(self, plugin_id: str) -> None:
        """Release one invocation reservation."""
        current = self._concurrent.get(plugin_id, 0)
        self._concurrent[plugin_id] = max(0, current - 1)


class PluginQuotaExceededError(RuntimeError):
    """Structured quota exhaustion error."""

    def __init__(self, plugin_id: str, limit: str) -> None:
        self.plugin_id = plugin_id
        self.limit = limit
        super().__init__(f"plugin {plugin_id} exceeded {limit}")


def canonical_plugin_json(payload: Mapping[str, Any]) -> bytes:
    """Return canonical package JSON bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    """Return lowercase SHA-256 hex."""
    return hashlib.sha256(data).hexdigest()


def _package_signature_payload(bundle: PluginPackageBundle) -> bytes:
    return canonical_plugin_json(
        {
            "manifest_digest": sha256_hex(bundle.canonical_manifest.encode()),
            "artifact_digest": bundle.artifact_digest,
        }
    )


def _same_ed25519_key(left: Ed25519PublicKey, right: Ed25519PublicKey) -> bool:
    return left.public_bytes_raw() == right.public_bytes_raw()


def _load_ed25519_public_key(pem: str) -> Ed25519PublicKey:
    public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(public_key, Ed25519PublicKey):
        raise PluginTrustGateError("trusted marketplace key must be Ed25519")
    return public_key
