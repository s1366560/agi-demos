#!/usr/bin/env python3
"""Inspect or explicitly upgrade one scope's builtin reference during maintenance.

--auto applies an observed stale builtin reference in the same run using the
values just read from the database; the application service still enforces the
same CAS and verification checks as an explicit --apply.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.services.production_profile_baseline_upgrade_v2 import (  # noqa: E402
    upgrade_production_profile_baseline_v2,
)
from src.application.services.root_builtin_bundle_upgrade_service_v2 import (  # noqa: E402
    upgrade_root_builtin_bundle_v2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import (  # noqa: E402
    ScopedInstalledBundleLoaderV2,
)
from src.domain.model.plugins.generated_v2 import (  # noqa: E402
    BundleReferenceV2,
    DesiredBundleSetV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.database import (  # noqa: E402
    async_session_factory,
    engine,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (  # noqa: E402
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (  # noqa: E402
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import (  # noqa: E402
    production_bundle_sources_v2,
)


async def run(args: argparse.Namespace) -> None:
    if args.all_initialized_scopes:
        await _run_batch(args)
    else:
        await _run_scope(args)


async def _run_batch(args: argparse.Namespace) -> None:
    try:
        async with async_session_factory() as session:
            scopes = await PlatformPluginDesiredBundleSetRepositoryV2(
                session
            ).list_initialized_scopes()
        for scope in scopes:
            print(
                json.dumps(
                    {
                        "maintenance_scope": {
                            "kind": scope.kind.value,
                            "tenant_id": scope.tenant_id,
                            "project_id": scope.project_id,
                            "session_id": scope.session_id,
                        }
                    }
                )
            )
            scoped_args = argparse.Namespace(
                **{
                    **vars(args),
                    "all_initialized_scopes": False,
                    "scope_kind": scope.kind.value,
                    "tenant_id": scope.tenant_id,
                    "project_id": scope.project_id,
                    "session_id": scope.session_id,
                }
            )
            # Each owner is a complete transaction. A failure leaves that owner's
            # source, desired head, and last-good publication untouched; stop here.
            await _run_scope(scoped_args)
    finally:
        await engine.dispose()


def _builtin_reference(
    desired: DesiredBundleSetV2, replacement: BundleReferenceV2, *, auto: bool
) -> BundleReferenceV2 | None:
    current = next(
        (item for item in desired.bundles if item.bundle_id == replacement.bundle_id), None
    )
    if auto and (current is None or current.source != replacement.source):
        return None
    if current is None:
        raise ValueError(f"desired set has no {replacement.bundle_id} builtin reference to upgrade")
    return current


async def _run_scope(args: argparse.Namespace) -> None:
    sources = production_bundle_sources_v2()
    replacement = sources.desired_set.bundles[0]
    scope = ScopeV2(
        kind=ScopeKindV2(args.scope_kind),
        tenant_id=args.tenant_id,
        project_id=args.project_id,
        session_id=args.session_id,
    )
    try:
        async with async_session_factory() as session:
            head = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
                scope
            )
            if head is None:
                if args.auto:
                    print(json.dumps({"status": "uninitialized-scope"}))
                    return
                raise ValueError("scope has not been initialized")
            current = _builtin_reference(head.desired_set, replacement, auto=args.auto)
            if current is None:
                print(json.dumps({"status": "skipped", "reason_code": "builtin_reference_absent"}))
                return
            reference = head.desired_set.profile_source
            profile_receipt = None
            if args.upgrade_profile_baseline:
                source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
                    scope=scope,
                    source_id=reference.source_id,
                    revision=reference.revision,
                    digest=reference.digest,
                )
                if source is None:
                    raise ValueError("the existing exact scoped ProfileSource is unavailable")
                candidate = upgrade_production_profile_baseline_v2(source, sources.profile_source)
                profile_receipt = {
                    "source_id": source.source_id,
                    "old_revision": source.revision,
                    "new_revision": candidate.revision,
                    "old_digest": source.digest,
                    "new_digest": candidate.digest,
                    "baseline_layer": "memstack-production-target-hosts",
                    "preserved_overlay_layers": [
                        layer.layer_id
                        for layer in source.layers
                        if layer.layer_id != "memstack-production-target-hosts"
                    ],
                    "baseline_replacements_and_disabled_ids_preserved": True,
                }
            print(
                json.dumps(
                    {
                        "desired_revision": head.desired_set.revision,
                        "bundle_id": current.bundle_id,
                        "old_digest": current.digest,
                        "new_digest": replacement.digest,
                        **(
                            {"profile_baseline": profile_receipt}
                            if profile_receipt is not None
                            else {"profile_source_preserved": reference.source_id}
                        ),
                    }
                )
            )
            if not args.apply and not args.auto:
                return
            if args.auto:
                if current == replacement and (
                    profile_receipt is None
                    or profile_receipt["old_digest"] == profile_receipt["new_digest"]
                ):
                    print(json.dumps({"status": "up-to-date"}))
                    return
                expected_revision = head.desired_set.revision
            else:
                expected_revision = args.expected_revision
                if current.digest != args.expected_digest:
                    raise ValueError(
                        "builtin digest differs from the explicitly expected old digest"
                    )
                if args.upgrade_profile_baseline and (
                    reference.revision != args.expected_source_revision
                    or reference.digest != args.expected_source_digest
                ):
                    raise ValueError(
                        "profile source differs from the explicitly expected reference"
                    )
            loader = ScopedInstalledBundleLoaderV2(
                session_factory=async_session_factory,
                production_sources=sources,
                trusted_public_keys=tuple(args.trusted_public_key),
                allowed_registries=frozenset(args.allowed_registry),
            )
            record = await upgrade_root_builtin_bundle_v2(
                session,
                sources=sources,
                load_verified_bundle=loader,
                expected_revision=expected_revision,
                expected_bundle=current,
                actor_id=args.actor_id,
                scope=scope,
                upgrade_profile_baseline=args.upgrade_profile_baseline,
                expected_profile_source=reference if args.upgrade_profile_baseline else None,
            )
            await session.commit()
            print(json.dumps({"upgraded_desired_revision": record.desired_set.revision}))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--apply", action="store_true")
    _ = parser.add_argument(
        "--auto",
        action="store_true",
        help="upgrade an observed stale builtin reference in one run (CAS still enforced)",
    )
    _ = parser.add_argument(
        "--scope-kind", choices=[kind.value for kind in ScopeKindV2], default="root"
    )
    _ = parser.add_argument("--tenant-id")
    _ = parser.add_argument("--project-id")
    _ = parser.add_argument("--session-id")
    _ = parser.add_argument(
        "--all-initialized-scopes",
        action="store_true",
        help="inspect or --auto upgrade every existing owner, root first, with a CAS per owner",
    )
    _ = parser.add_argument("--expected-revision", type=int)
    _ = parser.add_argument("--expected-digest")
    _ = parser.add_argument(
        "--upgrade-profile-baseline",
        action="store_true",
        help="explicitly upgrade the production target-host layer, preserving overlays",
    )
    _ = parser.add_argument("--expected-source-revision", type=int)
    _ = parser.add_argument("--expected-source-digest")
    _ = parser.add_argument("--actor-id")
    _ = parser.add_argument("--trusted-public-key", action="append", default=[])
    _ = parser.add_argument("--allowed-registry", action="append", default=[])
    args = parser.parse_args()
    if args.apply and args.auto:
        parser.error("--apply and --auto are mutually exclusive")
    if args.all_initialized_scopes and (
        args.apply
        or args.scope_kind != "root"
        or args.tenant_id
        or args.project_id
        or args.session_id
    ):
        parser.error("--all-initialized-scopes cannot be combined with --apply or one scope")
    if args.auto and (
        args.expected_revision is not None
        or args.expected_digest
        or args.expected_source_revision is not None
        or args.expected_source_digest
    ):
        parser.error("--auto does not accept explicit expected references")
    if args.apply and not (
        args.expected_revision is not None and args.expected_digest and args.actor_id
    ):
        parser.error("--apply requires --expected-revision, --expected-digest and --actor-id")
    if args.auto and not args.actor_id:
        parser.error("--auto requires --actor-id")
    if (
        args.apply
        and args.upgrade_profile_baseline
        and not (args.expected_source_revision is not None and args.expected_source_digest)
    ):
        parser.error("--apply --upgrade-profile-baseline requires an expected source reference")
    if not args.upgrade_profile_baseline and (
        args.expected_source_revision is not None or args.expected_source_digest
    ):
        parser.error("expected source references require --upgrade-profile-baseline")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
