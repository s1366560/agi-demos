"""Runtime artifact attestation and load-order tests for plugin protocol v2."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    ArtifactReferenceV2,
    DataPlaneTargetV2,
    EventContractsV2,
    PluginContractV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    QuotaV2,
    RestartPolicyV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    ServiceContractV2,
    ServiceProvidedV2,
    TrustKindV2,
)
from src.infrastructure.plugins.v2.artifacts import (
    RepositoryPythonArtifactResolverV2,
    ResolvedPluginArtifactV2,
)
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import ModuleCatalogEntryV2

_MODULE_REF = "builtin://tests/artifact-attestation"
_ENTRYPOINT = "artifact_fixture_v2:apply"
_SOURCE = "repo+python://artifact_fixture_v2.py"


def _contract() -> PluginContractV2:
    return PluginContractV2(
        services=ServiceContractV2(
            provides=(ServiceProvidedV2(service="service:attested", version="1.0.0"),),
            requires=(),
        ),
        events=EventContractsV2(emits=(), handles=()),
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
        },
    )


def _snapshot(source_bytes: bytes, *, artifact_digest: str | None = None):
    contract = _contract()
    digest = artifact_digest or artifact_digest_v2(source_bytes)
    module = PluginModuleV2(
        module_ref=_MODULE_REF,
        entrypoint=_ENTRYPOINT,
        artifact=ArtifactReferenceV2(digest=digest, source=_SOURCE),
        targets=(DataPlaneTargetV2.PYTHON,),
        contract=contract,
        contract_digest=plugin_contract_digest_v2(contract),
    )
    manifest = PluginManifestV2(
        schema_version=2,
        plugin_id="artifact-attestation-tests",
        version="1.0.0",
        runtime=RuntimeKindV2.PYTHON_TRUSTED,
        trust=TrustKindV2.BUILTIN,
        modules=(module,),
        permissions=(),
        quotas=QuotaV2(),
    )
    entry = ProfileEntryV2(
        entry_id="attested",
        parent_entry_id=None,
        plugin_ref=manifest.plugin_id,
        module_ref=module.module_ref,
        enabled=True,
        config={},
        inject={},
        isolate={},
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        permissions=(),
        quotas=QuotaV2(),
        restart_policy=RestartPolicyV2.HOT_GENERATION,
    )
    return build_profile_snapshot_v2(
        profile_id="artifact-attestation-tests",
        generation=1,
        manifests=(manifest,),
        entries=(entry,),
    )


def _catalog(snapshot) -> dict[str, ModuleCatalogEntryV2]:
    manifest = snapshot.manifests[0]
    module = manifest.modules[0]
    return {
        module.module_ref: ModuleCatalogEntryV2(
            plugin_id=manifest.plugin_id,
            plugin_version=manifest.version,
            module_ref=module.module_ref,
            entrypoint=module.entrypoint,
            artifact_source=module.artifact.source,
            artifact_digest=module.artifact.digest,
            targets=module.targets,
            contract_digest=module.contract_digest,
        )
    }


class _TrackingResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2:
        self.calls.append(module.module_ref)
        return ResolvedPluginArtifactV2(
            module_ref=module.module_ref,
            entrypoint=module.entrypoint,
            source=module.artifact.source,
            canonical_bytes=b"unused",
            load=lambda: (_ for _ in ()).throw(AssertionError("entrypoint must not load")),
        )


@pytest.mark.unit
async def test_catalog_mismatch_rejects_before_artifact_resolution() -> None:
    source_bytes = b"def apply(context, config):\n    return None\n"
    snapshot = _snapshot(source_bytes)
    catalog = _catalog(snapshot)
    catalog[_MODULE_REF] = replace(
        catalog[_MODULE_REF],
        artifact_digest=f"sha256:{'0' * 64}",
    )
    resolver = _TrackingResolver()

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(target_catalog=catalog, artifact_resolver=resolver).stage(snapshot)

    assert error.value.code == "artifact_digest_mismatch"
    assert resolver.calls == []


@pytest.mark.unit
async def test_catalog_target_mismatch_rejects_before_artifact_resolution() -> None:
    source_bytes = b"def apply(context, config):\n    return None\n"
    snapshot = _snapshot(source_bytes)
    catalog = _catalog(snapshot)
    catalog[_MODULE_REF] = replace(
        catalog[_MODULE_REF],
        targets=(DataPlaneTargetV2.PYTHON, DataPlaneTargetV2.RUST_SERVER),
    )
    resolver = _TrackingResolver()

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(target_catalog=catalog, artifact_resolver=resolver).stage(snapshot)

    assert error.value.code == "catalog_module_mismatch"
    assert resolver.calls == []


@pytest.mark.unit
async def test_actual_byte_mismatch_rejects_before_python_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"def apply(context, config):\n    context.provide('service:attested', True)\n"
    (tmp_path / "artifact_fixture_v2.py").write_bytes(source_bytes)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("artifact_fixture_v2", None)
    snapshot = _snapshot(source_bytes, artifact_digest=f"sha256:{'1' * 64}")

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(
            target_catalog=_catalog(snapshot),
            artifact_resolver=RepositoryPythonArtifactResolverV2(tmp_path),
        ).stage(snapshot)

    assert error.value.code == "artifact_digest_mismatch"
    assert "artifact_fixture_v2" not in sys.modules


@pytest.mark.unit
async def test_entry_preflight_rejects_before_python_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"def apply(context, config):\n    context.provide('service:attested', True)\n"
    (tmp_path / "artifact_fixture_v2.py").write_bytes(source_bytes)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("artifact_fixture_v2", None)
    snapshot = _snapshot(source_bytes)
    object.__setattr__(snapshot.entries[0], "config", {"unexpected": True})

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(
            target_catalog=_catalog(snapshot),
            artifact_resolver=RepositoryPythonArtifactResolverV2(tmp_path),
        ).stage(snapshot)

    assert error.value.code == "invalid_module_config"
    assert "artifact_fixture_v2" not in sys.modules


@pytest.mark.unit
async def test_attested_bytes_load_entrypoint_and_activate_only_after_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"def apply(context, config):\n    context.provide('service:attested', True)\n"
    (tmp_path / "artifact_fixture_v2.py").write_bytes(source_bytes)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("artifact_fixture_v2", None)
    snapshot = _snapshot(source_bytes)

    generation = await LoaderV2(
        target_catalog=_catalog(snapshot),
        artifact_resolver=RepositoryPythonArtifactResolverV2(tmp_path),
    ).stage(snapshot)

    assert (
        generation.resolve(
            "service:attested",
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        is True
    )
    assert "artifact_fixture_v2" in sys.modules
    await generation.dispose()
