"""Plugin trust gate, package verification, and resource quota enforcement."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
)
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
        if manifest.trust == PluginTrust.UNTRUSTED:
            non_tool = sorted(
                {capability.kind.value for capability in manifest.provides}
                - {CapabilityKind.TOOL.value}
            )
            if non_tool:
                return self._deny(
                    manifest,
                    "untrusted plugin may only provide tool capabilities; "
                    f"got {','.join(non_tool)}",
                    frozenset(),
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
        self._usage: dict[str, _PluginQuotaUsage] = {}
        self._lock = RLock()

    def acquire(
        self,
        plugin_id: str,
        *,
        output_bytes: int = 0,
        wasm_fuel: int = 0,
        wasm_memory_bytes: int = 0,
        wall_time_ms: int = 0,
        network_requests: int = 1,
        storage_bytes: int = 0,
        usd_micros: int = 0,
    ) -> None:
        """Reserve one invocation and every declared resource atomically."""
        values = {
            "output_bytes": output_bytes,
            "wasm_fuel": wasm_fuel,
            "wasm_memory_bytes": wasm_memory_bytes,
            "wall_time_ms": wall_time_ms,
            "network_requests": network_requests,
            "storage_bytes": storage_bytes,
            "usd_micros": usd_micros,
        }
        negative = sorted(name for name, value in values.items() if value < 0)
        if negative:
            raise ValueError(f"quota reservations cannot be negative: {negative}")
        quota = self._quotas.get(plugin_id)
        if quota is None:
            return
        now = time.monotonic()
        with self._lock:
            usage = self._usage.get(plugin_id)
            if usage is None:
                usage = _PluginQuotaUsage(window_started=time.monotonic())
                self._usage[plugin_id] = usage
            if now - usage.window_started >= 60:
                usage.window_started = now
                usage.window_requests = 0

            checks = (
                (
                    quota.max_concurrent_calls is not None
                    and usage.concurrent >= quota.max_concurrent_calls,
                    "max_concurrent_calls",
                ),
                (
                    quota.max_output_bytes is not None
                    and (
                        output_bytes > quota.max_output_bytes
                        or usage.output_bytes + output_bytes > quota.max_output_bytes
                    ),
                    "max_output_bytes",
                ),
                (
                    quota.max_wasm_fuel is not None and wasm_fuel > quota.max_wasm_fuel,
                    "max_wasm_fuel",
                ),
                (
                    quota.max_wasm_memory_bytes is not None
                    and wasm_memory_bytes > quota.max_wasm_memory_bytes,
                    "max_wasm_memory_bytes",
                ),
                (
                    quota.max_wall_time_ms is not None and wall_time_ms > quota.max_wall_time_ms,
                    "max_wall_time_ms",
                ),
                (
                    quota.max_network_requests_per_minute is not None
                    and (
                        network_requests > quota.max_network_requests_per_minute
                        or usage.window_requests + network_requests
                        > quota.max_network_requests_per_minute
                    ),
                    "max_network_requests_per_minute",
                ),
                (
                    quota.max_storage_bytes is not None
                    and usage.storage_bytes + storage_bytes > quota.max_storage_bytes,
                    "max_storage_bytes",
                ),
                (
                    quota.max_monthly_usd is not None
                    and usage.usd_micros + usd_micros > self._monthly_micros(quota),
                    "max_monthly_usd",
                ),
            )
            for exceeded, limit in checks:
                if exceeded:
                    raise PluginQuotaExceededError(plugin_id, limit)

            usage.concurrent += 1
            usage.window_requests += network_requests
            usage.output_bytes += output_bytes
            usage.storage_bytes += storage_bytes
            usage.usd_micros += usd_micros

    def release(self, plugin_id: str, *, wall_time_ms: int = 0) -> None:
        """Release one reservation and enforce the observed wall-clock bound."""
        with self._lock:
            usage = self._usage.get(plugin_id)
            if usage is None:
                return
            usage.concurrent = max(0, usage.concurrent - 1)
            quota = self._quotas.get(plugin_id)
            if (
                wall_time_ms >= 0
                and quota is not None
                and quota.max_wall_time_ms is not None
                and wall_time_ms > quota.max_wall_time_ms
            ):
                raise PluginQuotaExceededError(plugin_id, "max_wall_time_ms")

    @staticmethod
    def _monthly_micros(quota: ResourceQuota) -> int:
        if quota.max_monthly_usd is None:
            return 0
        return int(Decimal(str(quota.max_monthly_usd)) * Decimal(1_000_000))


@dataclass
class _PluginQuotaUsage:
    window_started: float
    concurrent: int = 0
    window_requests: int = 0
    output_bytes: int = 0
    storage_bytes: int = 0
    usd_micros: int = 0


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
