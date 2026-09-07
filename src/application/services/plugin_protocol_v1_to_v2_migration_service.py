"""One-shot, offline conversion from frozen V1 rows to V2 DesiredBundleSet heads."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import NoReturn

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    BundleReferenceV2,
    DesiredBundleSetV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
    TrustKindV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
    PlatformPluginProfileSourceV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    LegacyPluginDesiredStateExportV1,
    LegacyPluginDesiredStateRowV1,
    PlatformPluginV1MigrationRepository,
    PlatformPluginV1MigrationRepositoryError,
    digest_payload_v1_to_v2,
    scope_v2_to_payload,
)
from src.infrastructure.plugins.v2.composer import ProfileCompositionV2Error, compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import (
    ProfileSourceCompositionV2Error,
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_BUNDLE_ID_V2,
    ProductionBundleSourcesV2,
)
from src.infrastructure.plugins.v2.protocol import PluginProtocolV2Error, parse_bundle_manifest_v2
from src.infrastructure.plugins.v2.scope import scope_key_v2

from .plugin_protocol_v1_to_v2_migration_contract import (
    MigrationDecisionV1ToV2,
    PluginProtocolV1ToV2Action,
    PluginProtocolV1ToV2MigrationDocument,
    PluginProtocolV1ToV2MigrationError,
    parse_plugin_v1_to_v2_migration_document,
    plugin_v1_to_v2_decision_output_digest,
)

_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"


@dataclass(frozen=True, kw_only=True)
class PluginProtocolV1ToV2ScopePlan:
    scope: ScopeV2
    before: PlatformPluginDesiredBundleSetRecordV2 | None
    desired_set: DesiredBundleSetV2
    changed: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "scope": scope_v2_to_payload(self.scope),
            "before_revision": None if self.before is None else self.before.desired_set.revision,
            "before_digest": None if self.before is None else self.before.desired_set.digest,
            "after_revision": self.desired_set.revision,
            "after_digest": self.desired_set.digest,
            "changed": self.changed,
        }


@dataclass(frozen=True, kw_only=True)
class PluginProtocolV1ToV2MigrationPlan:
    document: PluginProtocolV1ToV2MigrationDocument
    source: LegacyPluginDesiredStateExportV1
    scopes: tuple[PluginProtocolV1ToV2ScopePlan, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "migration_id": self.document.migration_id,
            "source_digest": self.source.digest,
            "mapping_digest": self.document.mapping_digest,
            "source_row_count": len(self.source.rows),
            "scopes": [scope.to_payload() for scope in self.scopes],
        }


@dataclass(frozen=True, kw_only=True)
class PluginProtocolV1ToV2MigrationResult:
    audit_record_id: str
    report: dict[str, object]


class PluginProtocolV1ToV2MigrationService:
    """Validate explicit judgments, atomically append V2 heads, and retain V1 rows."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        migration_repository: PlatformPluginV1MigrationRepository,
        desired_repository: PlatformPluginDesiredBundleSetRepositoryV2,
        governance_repository: PlatformPluginGovernanceRepository,
        production_sources: ProductionBundleSourcesV2,
        source_repository: PlatformPluginProfileSourceRepositoryV2 | None = None,
    ) -> None:
        self._migration_repository = migration_repository
        self._desired_repository = desired_repository
        self._governance_repository = governance_repository
        self._production_sources = production_sources
        self._source_repository = source_repository

    async def export_template(self, *, migration_id: str) -> dict[str, object]:
        """Export a secret-free, content-addressed source and incomplete mapping template."""
        source = await self._export_source()
        scopes = {scope_key_v2(ScopeV2(kind=ScopeKindV2.ROOT)): ScopeV2(kind=ScopeKindV2.ROOT)}
        for row in source.rows:
            scopes[scope_key_v2(row.scope)] = row.scope
        target_heads: list[dict[str, object]] = []
        for key in sorted(scopes):
            scope = scopes[key]
            head = await self._desired_repository.current_desired_set(scope)
            target_heads.append(
                {
                    "scope": scope_v2_to_payload(scope),
                    "expected_revision": None if head is None else head.desired_set.revision,
                    "expected_digest": None if head is None else head.desired_set.digest,
                }
            )
        return {
            "schema_version": 1,
            "migration_id": migration_id,
            "source": source.to_payload(),
            "target_heads": target_heads,
            "decisions": [
                {
                    "source_row_id": row.source_row_id,
                    "source_row_digest": row.source_row_digest,
                    "action": None,
                    "target_bundle": None,
                    "judgment": None,
                }
                for row in source.rows
            ],
        }

    async def plan(self, payload: object) -> PluginProtocolV1ToV2MigrationPlan:
        """Validate source/target concurrency and every structured mapping judgment."""
        document = parse_plugin_v1_to_v2_migration_document(payload)
        source = await self._export_source()
        if document.source != source.to_payload():
            _fail(
                "migration_source_changed",
                "V1 desired state differs from the exported source snapshot",
            )
        rows_by_id = {row.source_row_id: row for row in source.rows}
        decisions_by_id = {decision.source_row_id: decision for decision in document.decisions}
        missing = sorted(rows_by_id.keys() - decisions_by_id.keys())
        extras = sorted(decisions_by_id.keys() - rows_by_id.keys())
        if missing:
            _fail("migration_decision_missing", "one or more V1 rows have no explicit decision")
        if extras:
            _fail("migration_decision_unknown", "mapping contains an unknown V1 source row")
        for source_row_id, row in rows_by_id.items():
            if decisions_by_id[source_row_id].source_row_digest != row.source_row_digest:
                _fail("migration_source_changed", "mapping row digest differs from V1 source")

        scope_rows: dict[str, list[tuple[LegacyPluginDesiredStateRowV1, MigrationDecisionV1ToV2]]]
        scope_rows = {}
        scopes = {scope_key_v2(ScopeV2(kind=ScopeKindV2.ROOT)): ScopeV2(kind=ScopeKindV2.ROOT)}
        for row in source.rows:
            key = scope_key_v2(row.scope)
            scopes[key] = row.scope
            scope_rows.setdefault(key, []).append((row, decisions_by_id[row.source_row_id]))
        expected_heads = {scope_key_v2(item.scope): item for item in document.target_heads}
        if set(expected_heads) != set(scopes):
            _fail(
                "migration_target_heads_invalid",
                "target_heads must exactly cover root and every resolved V1 scope",
            )

        plans: list[PluginProtocolV1ToV2ScopePlan] = []
        for key in sorted(scopes):
            scope = scopes[key]
            current = await self._desired_repository.current_desired_set(scope)
            expected = expected_heads[key]
            actual_head = (
                None if current is None else current.desired_set.revision,
                None if current is None else current.desired_set.digest,
            )
            if actual_head != (expected.expected_revision, expected.expected_digest):
                _fail(
                    "migration_target_head_changed",
                    "V2 desired-state head changed after the mapping export",
                )
            plans.append(
                await self._scope_plan(
                    scope=scope,
                    current=current,
                    rows=scope_rows.get(key, []),
                )
            )
        return PluginProtocolV1ToV2MigrationPlan(
            document=document,
            source=source,
            scopes=tuple(plans),
        )

    async def execute(
        self,
        payload: object,
        *,
        actor_id: str,
    ) -> PluginProtocolV1ToV2MigrationResult:
        """Append all planned V2 scope heads and one audit record in the caller transaction."""
        if not actor_id.strip():
            _fail("migration_actor_invalid", "actor_id is required")
        document = parse_plugin_v1_to_v2_migration_document(payload)
        existing = await self._migration_repository.get_completed_run(document.migration_id)
        if existing is not None:
            if (
                existing.source_digest != str(document.source["digest"])
                or existing.mapping_digest != document.mapping_digest
            ):
                _fail(
                    "migration_id_conflict",
                    "migration_id already belongs to different conversion evidence",
                )
            return PluginProtocolV1ToV2MigrationResult(
                audit_record_id=existing.record_id,
                report=dict(existing.report),
            )

        plan = await self.plan(payload)
        scope_reports: list[dict[str, object]] = []
        output_scopes: list[dict[str, object]] = []
        for scope_plan in plan.scopes:
            if scope_plan.changed:
                persisted_record = await self._desired_repository.record_desired_set(
                    scope=scope_plan.scope,
                    desired_set=scope_plan.desired_set,
                    expected_revision=(
                        None
                        if scope_plan.before is None
                        else scope_plan.before.desired_set.revision
                    ),
                    actor_id=actor_id,
                )
            else:
                before = scope_plan.before
                if before is None:  # pragma: no cover - changed invariant
                    raise RuntimeError("unchanged conversion scope has no persisted head")
                persisted_record = before
            scope_report = {
                **scope_plan.to_payload(),
                "record_id": persisted_record.record_id,
            }
            scope_reports.append(scope_report)
            output_scopes.append(
                {
                    "scope": scope_v2_to_payload(scope_plan.scope),
                    "revision": persisted_record.desired_set.revision,
                    "digest": persisted_record.desired_set.digest,
                }
            )
        output_digest = digest_payload_v1_to_v2(
            {
                "schema_version": 1,
                "migration_id": document.migration_id,
                "source_digest": plan.source.digest,
                "mapping_digest": document.mapping_digest,
                "scopes": output_scopes,
            }
        )
        report: dict[str, object] = {
            "schema_version": 1,
            "migration_id": document.migration_id,
            "source_digest": plan.source.digest,
            "mapping_digest": document.mapping_digest,
            "output_digest": output_digest,
            "actor_id": actor_id,
            "source_row_count": len(plan.source.rows),
            "decisions": [decision.to_payload() for decision in document.decisions],
            "scopes": scope_reports,
        }
        audit = await self._migration_repository.record_completed_run(
            migration_id=document.migration_id,
            source_digest=plan.source.digest,
            mapping_digest=document.mapping_digest,
            output_digest=output_digest,
            actor_id=actor_id,
            report=report,
        )
        return PluginProtocolV1ToV2MigrationResult(
            audit_record_id=audit.record_id,
            report=dict(audit.report),
        )

    async def _scope_plan(
        self,
        *,
        scope: ScopeV2,
        current: PlatformPluginDesiredBundleSetRecordV2 | None,
        rows: list[tuple[LegacyPluginDesiredStateRowV1, MigrationDecisionV1ToV2]],
    ) -> PluginProtocolV1ToV2ScopePlan:
        baseline = self._production_sources.desired_set
        desired = baseline if current is None else current.desired_set
        source = await self._validate_target_baseline(desired, scope=scope)
        bundles = list(desired.bundles)
        operated_bundle_ids: set[str] = set()
        for row, decision in rows:
            await self._apply_decision(
                bundles=bundles,
                operated_bundle_ids=operated_bundle_ids,
                row=row,
                decision=decision,
            )

        changed = current is None or tuple(bundles) != current.desired_set.bundles
        if current is not None and not changed:
            result = current.desired_set
        else:
            revision = 1 if current is None else current.desired_set.revision + 1
            result = replace(
                desired,
                revision=revision,
                bundles=tuple(bundles),
                digest=_ZERO_DIGEST_V2,
            )
            result = replace(result, digest=desired_bundle_set_digest_v2(result))
        await self._validate_source_composition(result, source=source, scope=scope)
        return PluginProtocolV1ToV2ScopePlan(
            scope=scope,
            before=current,
            desired_set=result,
            changed=changed,
        )

    async def _apply_decision(
        self,
        *,
        bundles: list[BundleReferenceV2],
        operated_bundle_ids: set[str],
        row: LegacyPluginDesiredStateRowV1,
        decision: MigrationDecisionV1ToV2,
    ) -> None:
        self._validate_action_shape(row, decision)
        target = decision.target_bundle
        if target is None:
            return
        if target.bundle_id == PRODUCTION_BASE_BUNDLE_ID_V2:
            _fail(
                "migration_protected_bundle",
                "conversion decisions cannot mutate the production base Bundle",
            )
        if target.bundle_id in operated_bundle_ids:
            _fail(
                "migration_bundle_decision_conflict",
                "multiple V1 rows operate on the same Bundle within one scope",
            )
        operated_bundle_ids.add(target.bundle_id)
        if decision.action in {
            PluginProtocolV1ToV2Action.ADD_BUNDLE,
            PluginProtocolV1ToV2Action.REPLACE_BUNDLE,
        }:
            _ = await self._validate_target_bundle(target)

        positions = {item.bundle_id: index for index, item in enumerate(bundles)}
        position = positions.get(target.bundle_id)
        if decision.action is PluginProtocolV1ToV2Action.ADD_BUNDLE:
            if position is None:
                bundles.append(target)
            elif bundles[position] != target:
                _fail(
                    "migration_bundle_add_conflict",
                    "add_bundle cannot replace a different current Bundle reference",
                )
            return
        if decision.action is PluginProtocolV1ToV2Action.REPLACE_BUNDLE:
            if position is None:
                _fail(
                    "migration_bundle_replace_missing",
                    "replace_bundle requires an existing exact Bundle id",
                )
            bundles[position] = target
            return
        if decision.action is PluginProtocolV1ToV2Action.REMOVE_BUNDLE and position is not None:
            if bundles[position] != target:
                _fail(
                    "migration_bundle_remove_conflict",
                    "remove_bundle reference differs from the current V2 head",
                )
            del bundles[position]

    async def _validate_target_baseline(
        self, desired: DesiredBundleSetV2, *, scope: ScopeV2
    ) -> ProfileSourceV2:
        baseline = self._production_sources.desired_set
        if not desired.bundles or desired.bundles[0] != baseline.bundles[0]:
            _fail(
                "migration_target_baseline_conflict",
                "V2 target head does not retain the exact production base Bundle first",
            )
        reference = desired.profile_source
        source = None
        if self._source_repository is not None:
            try:
                source = await self._source_repository.read_exact(
                    scope=scope,
                    source_id=reference.source_id,
                    revision=reference.revision,
                    digest=reference.digest,
                )
            except (PlatformPluginProfileSourceV2Error, PluginProtocolV2Error) as exc:
                raise PluginProtocolV1ToV2MigrationError(
                    "migration_target_profile_source_conflict",
                    "V2 target exact ProfileSource is invalid",
                ) from exc
        if source is None:
            if reference != baseline.profile_source:
                _fail(
                    "migration_target_profile_source_conflict",
                    "V2 target exact ProfileSource is missing",
                )
            source = self._production_sources.profile_source
        await self._validate_source_composition(desired, source=source, scope=scope)
        return source

    async def _validate_source_composition(
        self, desired: DesiredBundleSetV2, *, source: ProfileSourceV2, scope: ScopeV2
    ) -> None:
        # Offline structural verification, not execution or signature authorization.
        for layer in source.layers:
            if any(
                getattr(layer.scope, field) is not None
                and getattr(layer.scope, field) != getattr(scope, field)
                for field in ("tenant_id", "project_id", "session_id")
            ):
                _fail(
                    "migration_target_profile_source_conflict",
                    "V2 target ProfileSource layer is outside the requested scope ancestry",
                )
        bundles = [self._production_sources.bundle]
        for reference in desired.bundles[1:]:
            bundles.append(await self._validate_target_bundle(reference))
        try:
            composition = compose_profile_sources_v2(
                desired_set=desired,
                bundles=tuple(bundles),
                profile_source=source,
                scope=scope,
            )
            _ = compose_profile_v2(
                composition.document,
                {manifest.plugin_id: manifest for manifest in composition.manifests},
                generation=desired.revision,
            )
        except (
            ProfileSourceCompositionV2Error,
            ProfileCompositionV2Error,
            PluginProtocolV2Error,
        ) as exc:
            raise PluginProtocolV1ToV2MigrationError(
                "migration_target_profile_source_conflict",
                "V2 target ProfileSource does not compose with its exact Bundle set",
            ) from exc

    @staticmethod
    def _validate_action_shape(
        row: LegacyPluginDesiredStateRowV1,
        decision: MigrationDecisionV1ToV2,
    ) -> None:
        requires_bundle = decision.action in {
            PluginProtocolV1ToV2Action.ADD_BUNDLE,
            PluginProtocolV1ToV2Action.REPLACE_BUNDLE,
            PluginProtocolV1ToV2Action.REMOVE_BUNDLE,
        }
        if requires_bundle != (decision.target_bundle is not None):
            _fail(
                "migration_decision_invalid",
                "decision action and target_bundle are inconsistent",
            )
        enabled_actions = {
            PluginProtocolV1ToV2Action.ADD_BUNDLE,
            PluginProtocolV1ToV2Action.REPLACE_BUNDLE,
            PluginProtocolV1ToV2Action.RETAIN_BASELINE,
        }
        disabled_actions = {
            PluginProtocolV1ToV2Action.REMOVE_BUNDLE,
            PluginProtocolV1ToV2Action.OMIT_INACTIVE,
        }
        allowed = enabled_actions if row.enabled else disabled_actions
        if decision.action not in allowed:
            _fail(
                "migration_decision_invalid",
                "decision action does not preserve the V1 enabled state",
            )

    async def _validate_target_bundle(self, reference: BundleReferenceV2) -> BundleManifestV2:
        expected_source = f"marketplace://{reference.bundle_id}/{reference.version}"
        package = await self._governance_repository.get_package_version(
            reference.bundle_id,
            reference.version,
        )
        if (
            reference.source != expected_source
            or package is None
            or package.install_status != "installed"
            or package.revoked
            or package.security_scan_status != "passed"
            or not package.signature
            or not package.provenance
        ):
            _fail(
                "migration_target_bundle_unavailable",
                "target Bundle is not an installed, trusted protocol-v2 package",
            )
        try:
            bundle = parse_bundle_manifest_v2(package.manifest)
        except PluginProtocolV2Error as exc:
            raise PluginProtocolV1ToV2MigrationError(
                "migration_target_bundle_invalid",
                "target package does not contain a valid protocol-v2 Bundle",
            ) from exc
        if (
            bundle.bundle_id != reference.bundle_id
            or bundle.version != reference.version
            or bundle.digest != reference.digest
            or any(manifest.trust is TrustKindV2.BUILTIN for manifest in bundle.manifests)
        ):
            _fail(
                "migration_target_bundle_invalid",
                "target Bundle identity, digest, or trust differs from its mapping",
            )

        return bundle

    async def _export_source(self) -> LegacyPluginDesiredStateExportV1:
        try:
            return await self._migration_repository.export_source()
        except PlatformPluginV1MigrationRepositoryError as exc:
            raise PluginProtocolV1ToV2MigrationError(exc.code, str(exc)) from exc


def _fail(code: str, message: str) -> NoReturn:
    raise PluginProtocolV1ToV2MigrationError(code, message)


__all__ = [
    "PluginProtocolV1ToV2MigrationError",
    "PluginProtocolV1ToV2MigrationPlan",
    "PluginProtocolV1ToV2MigrationResult",
    "PluginProtocolV1ToV2MigrationService",
    "plugin_v1_to_v2_decision_output_digest",
]
