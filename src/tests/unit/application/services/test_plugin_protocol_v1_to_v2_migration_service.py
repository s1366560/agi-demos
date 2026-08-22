"""One-shot, explicit protocol-v1 desired-state conversion tests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.plugin_protocol_v1_to_v2_migration_service import (
    PluginProtocolV1ToV2MigrationError,
    PluginProtocolV1ToV2MigrationService,
    plugin_v1_to_v2_decision_output_digest,
)
from src.domain.model.plugins import PluginScope
from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    PlatformPluginDesiredStateModel,
    PlatformPluginV1MigrationRunModel,
    PlatformPluginV2DesiredBundleSetModel,
    Project,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    PlatformPluginV1MigrationRepository,
)
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    parse_profile_snapshot_v2,
)

pytestmark = pytest.mark.unit
_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"
_ROOT = Path(__file__).resolve().parents[5]


def _signed_bundle(bundle_id: str = "replacement-tools") -> BundleManifestV2:
    snapshot = parse_profile_snapshot_v2(
        json.loads(
            (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
        )
    )
    plugin_id = f"{bundle_id}-plugin"
    manifest = replace(
        snapshot.manifests[0],
        plugin_id=plugin_id,
        trust=TrustKindV2.SIGNED,
    )
    entry = replace(
        snapshot.entries[0],
        plugin_ref=plugin_id,
        module_ref=manifest.modules[0].module_ref,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    artifacts = tuple(
        BundleArtifactV2(
            artifact_id=f"{bundle_id}-{target.value}-{index}",
            target=target,
            path=f"artifacts/{target.value}/{index}.bin",
            digest=digest,
            size_bytes=1,
            media_type="application/octet-stream",
        )
        for index, (target, digest) in enumerate(
            dict.fromkeys(
                (target, module.artifact.digest)
                for module in manifest.modules
                for target in module.targets
            )
        )
    )
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id=bundle_id,
        version="1.0.0",
        manifests=(manifest,),
        layers=(
            ProfileLayerV2(
                layer_id=f"{bundle_id}-layer",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=(entry,),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=artifacts,
        signature="dGVzdC1zaWduYXR1cmU=",
        provenance="tests",
        digest=_ZERO_DIGEST_V2,
    )
    return replace(bundle, digest=bundle_manifest_digest_v2(bundle))


async def _install_target_bundle(db: AsyncSession, bundle: BundleManifestV2) -> None:
    await PlatformPluginGovernanceRepository(db).upsert_package(
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        publisher="migration-test-publisher",
        artifact_digest="a" * 64,
        artifact_registry="registry.example.test",
        artifact_repository=bundle.bundle_id,
        oci_manifest_digest="b" * 64,
        manifest=bundle_manifest_v2_to_payload(bundle),
        signature={"algorithm": "Ed25519", "signature_sha256": "c" * 64},
        provenance={"reference": bundle.provenance},
        security_scan_status="passed",
    )


def _bundle_reference(bundle: BundleManifestV2) -> dict[str, object]:
    return {
        "bundle_id": bundle.bundle_id,
        "version": bundle.version,
        "digest": bundle.digest,
        "source": f"marketplace://{bundle.bundle_id}/{bundle.version}",
    }


def _decide(
    template: dict[str, object],
    *,
    action: str,
    target_bundle: dict[str, object] | None,
) -> dict[str, object]:
    document = deepcopy(template)
    decisions = document["decisions"]
    assert isinstance(decisions, list) and len(decisions) == 1
    decision = decisions[0]
    assert isinstance(decision, dict)
    decision["action"] = action
    decision["target_bundle"] = target_bundle
    decision["judgment"] = {
        "agent_id": "plugin-migration-mapper",
        "tool_name": "plugin_v1_to_v2_map",
        "input_digest": decision["source_row_digest"],
        "output_digest": plugin_v1_to_v2_decision_output_digest(
            action=action,
            target_bundle=target_bundle,
        ),
        "rationale": "The exact legacy row is represented by this reviewed V2 Bundle decision.",
        "latency_ms": 12,
    }
    return document


def _service(db: AsyncSession) -> PluginProtocolV1ToV2MigrationService:
    return PluginProtocolV1ToV2MigrationService(
        migration_repository=PlatformPluginV1MigrationRepository(db),
        desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(db),
        governance_repository=PlatformPluginGovernanceRepository(db),
        production_sources=production_bundle_sources_v2(),
    )


async def test_explicit_mapping_is_atomic_audited_idempotent_and_secret_safe(
    db_session: AsyncSession,
) -> None:
    legacy_repository = PlatformPluginRepository(db_session)
    legacy = await legacy_repository.set_desired_state(
        plugin_id="legacy-tools",
        enabled=True,
        config={"api_token": "must-not-appear-in-export", "mode": "strict"},
    )
    bundle = _signed_bundle()
    await _install_target_bundle(db_session, bundle)
    service = _service(db_session)

    template = await service.export_template(migration_id="migration-001")

    assert "must-not-appear-in-export" not in str(template)
    source = template["source"]
    assert isinstance(source, dict)
    rows = source["rows"]
    assert isinstance(rows, list) and rows[0]["source_row_id"] == legacy.id
    assert rows[0]["config_keys"] == ["api_token", "mode"]
    mapping = _decide(
        template,
        action="add_bundle",
        target_bundle=_bundle_reference(bundle),
    )

    first = await service.execute(mapping, actor_id="platform-admin")
    repeated = await service.execute(mapping, actor_id="platform-admin")

    root = ScopeV2(kind=ScopeKindV2.ROOT)
    head = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(root)
    assert head is not None
    assert [item.bundle_id for item in head.desired_set.bundles] == [
        "memstack-platform-base",
        bundle.bundle_id,
    ]
    assert first.audit_record_id == repeated.audit_record_id
    assert first.report == repeated.report
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginV1MigrationRunModel))
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2DesiredBundleSetModel)
        )
        == 1
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginDesiredStateModel))
        == 1
    )


async def test_unmapped_or_drifted_source_fails_before_target_writes(
    db_session: AsyncSession,
) -> None:
    legacy_repository = PlatformPluginRepository(db_session)
    await legacy_repository.set_desired_state(
        plugin_id="legacy-tools",
        enabled=True,
        config={"mode": "strict"},
    )
    service = _service(db_session)
    template = await service.export_template(migration_id="migration-002")

    with pytest.raises(PluginProtocolV1ToV2MigrationError) as unmapped:
        await service.plan(template)
    assert unmapped.value.code == "migration_decision_missing"

    mapping = _decide(template, action="retain_baseline", target_bundle=None)
    await legacy_repository.set_desired_state(
        plugin_id="legacy-tools",
        enabled=True,
        config={"mode": "changed"},
    )
    with pytest.raises(PluginProtocolV1ToV2MigrationError) as drifted:
        await service.execute(mapping, actor_id="platform-admin")
    assert drifted.value.code == "migration_source_changed"
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginV1MigrationRunModel))
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2DesiredBundleSetModel)
        )
        == 0
    )


async def test_mapping_scope_fields_and_migration_id_evidence_are_exact(
    db_session: AsyncSession,
) -> None:
    await PlatformPluginRepository(db_session).set_desired_state(
        plugin_id="legacy-tools",
        enabled=True,
        config={},
    )
    service = _service(db_session)
    template = await service.export_template(migration_id="migration-exact-evidence")
    mapping = _decide(template, action="retain_baseline", target_bundle=None)
    invalid_scope = deepcopy(mapping)
    target_heads = invalid_scope["target_heads"]
    assert isinstance(target_heads, list)
    target_head = target_heads[0]
    assert isinstance(target_head, dict)
    scope = target_head["scope"]
    assert isinstance(scope, dict)
    scope["implementation_hint"] = "must-not-be-accepted"

    with pytest.raises(PluginProtocolV1ToV2MigrationError) as malformed:
        await service.plan(invalid_scope)
    assert malformed.value.code == "migration_target_heads_invalid"

    first = await service.execute(mapping, actor_id="platform-admin")
    conflicting = deepcopy(mapping)
    decisions = conflicting["decisions"]
    assert isinstance(decisions, list)
    decision = decisions[0]
    assert isinstance(decision, dict)
    judgment = decision["judgment"]
    assert isinstance(judgment, dict)
    judgment["rationale"] = "A different reviewed rationale must produce different evidence."

    with pytest.raises(PluginProtocolV1ToV2MigrationError) as conflict:
        await service.execute(conflicting, actor_id="platform-admin")
    assert conflict.value.code == "migration_id_conflict"
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginV1MigrationRunModel))
        == 1
    )
    assert first.report["migration_id"] == "migration-exact-evidence"


async def test_target_head_change_and_untrusted_bundle_fail_closed(
    db_session: AsyncSession,
) -> None:
    await PlatformPluginRepository(db_session).set_desired_state(
        plugin_id="legacy-tools",
        enabled=True,
        config={},
    )
    service = _service(db_session)
    template = await service.export_template(migration_id="migration-003")
    missing_bundle = _signed_bundle("missing-bundle")
    mapping = _decide(
        template,
        action="add_bundle",
        target_bundle=_bundle_reference(missing_bundle),
    )

    with pytest.raises(PluginProtocolV1ToV2MigrationError) as unavailable:
        await service.plan(mapping)
    assert unavailable.value.code == "migration_target_bundle_unavailable"

    baseline = production_bundle_sources_v2().desired_set
    await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        desired_set=baseline,
        expected_revision=None,
        actor_id="concurrent-v2-writer",
    )
    mapping = _decide(template, action="retain_baseline", target_bundle=None)
    with pytest.raises(PluginProtocolV1ToV2MigrationError) as conflict:
        await service.plan(mapping)
    assert conflict.value.code == "migration_target_head_changed"


async def test_disabled_mapping_removes_only_the_exact_reviewed_bundle(
    db_session: AsyncSession,
) -> None:
    await PlatformPluginRepository(db_session).set_desired_state(
        plugin_id="legacy-tools",
        enabled=False,
        config={},
    )
    bundle = _signed_bundle()
    await _install_target_bundle(db_session, bundle)
    sources = production_bundle_sources_v2()
    reference = BundleReferenceV2(**_bundle_reference(bundle))
    current = replace(
        sources.desired_set,
        bundles=(*sources.desired_set.bundles, reference),
        digest=_ZERO_DIGEST_V2,
    )
    current = replace(current, digest=desired_bundle_set_digest_v2(current))
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    await repository.record_desired_set(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        desired_set=current,
        expected_revision=None,
        actor_id="existing-v2-state",
    )
    service = _service(db_session)
    template = await service.export_template(migration_id="migration-004")
    mapping = _decide(
        template,
        action="remove_bundle",
        target_bundle=_bundle_reference(bundle),
    )

    result = await service.execute(mapping, actor_id="platform-admin")

    head = await repository.current_desired_set(ScopeV2(kind=ScopeKindV2.ROOT))
    assert head is not None
    assert [item.bundle_id for item in head.desired_set.bundles] == ["memstack-platform-base"]
    assert head.desired_set.revision == current.revision + 1
    assert result.report["source_row_count"] == 1


async def test_scope_projection_is_structural_for_tenant_project_and_session(
    db_session: AsyncSession,
    test_user: User,
    test_tenant_db: Tenant,
    test_project_db: Project,
) -> None:
    tenant_id = str(test_tenant_db.id)
    project_id = str(test_project_db.id)
    user_id = str(test_user.id)
    conversation = Conversation(
        id="migration-session",
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
        title="Migration scope fixture",
    )
    db_session.add(conversation)
    await db_session.flush()
    legacy = PlatformPluginRepository(db_session)
    for scope, scope_id in (
        (PluginScope.TENANT, tenant_id),
        (PluginScope.PROJECT, project_id),
        (PluginScope.SESSION, conversation.id),
    ):
        await legacy.set_desired_state(
            plugin_id=f"legacy-{scope.value}",
            enabled=True,
            config={},
            scope=scope,
            scope_id=scope_id,
        )
    service = _service(db_session)
    template = await service.export_template(migration_id="migration-005")
    mapping = deepcopy(template)
    decisions = mapping["decisions"]
    assert isinstance(decisions, list)
    for decision in decisions:
        assert isinstance(decision, dict)
        decision["action"] = "retain_baseline"
        decision["target_bundle"] = None
        decision["judgment"] = {
            "agent_id": "plugin-migration-mapper",
            "tool_name": "plugin_v1_to_v2_map",
            "input_digest": decision["source_row_digest"],
            "output_digest": plugin_v1_to_v2_decision_output_digest(
                action="retain_baseline",
                target_bundle=None,
            ),
            "rationale": "The reviewed production baseline already owns this capability.",
            "latency_ms": 8,
        }

    await service.execute(mapping, actor_id="platform-admin")

    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    scopes = (
        ScopeV2(kind=ScopeKindV2.ROOT),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
        ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id),
        ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=conversation.id,
        ),
    )
    for scope in scopes:
        head = await repository.current_desired_set(scope)
        assert head is not None
        assert head.desired_set.bundles == production_bundle_sources_v2().desired_set.bundles
