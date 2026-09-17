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

from src.application.services.root_builtin_bundle_upgrade_service_v2 import (  # noqa: E402
    upgrade_root_builtin_bundle_v2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import (  # noqa: E402
    ScopedInstalledBundleLoaderV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2  # noqa: E402
from src.infrastructure.adapters.secondary.persistence.database import (  # noqa: E402
    async_session_factory,
    engine,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (  # noqa: E402
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import (  # noqa: E402
    production_bundle_sources_v2,
)


async def run(args: argparse.Namespace) -> None:
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
            current = next(
                item for item in head.desired_set.bundles if item.bundle_id == replacement.bundle_id
            )
            print(
                json.dumps(
                    {
                        "desired_revision": head.desired_set.revision,
                        "bundle_id": current.bundle_id,
                        "old_digest": current.digest,
                        "new_digest": replacement.digest,
                        "profile_source_preserved": head.desired_set.profile_source.source_id,
                    }
                )
            )
            if not args.apply and not args.auto:
                return
            if args.auto:
                if current == replacement:
                    print(json.dumps({"status": "up-to-date"}))
                    return
                expected_revision = head.desired_set.revision
            else:
                expected_revision = args.expected_revision
                if current.digest != args.expected_digest:
                    raise ValueError("builtin digest differs from the explicitly expected old digest")
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
    _ = parser.add_argument("--expected-revision", type=int)
    _ = parser.add_argument("--expected-digest")
    _ = parser.add_argument("--actor-id")
    _ = parser.add_argument("--trusted-public-key", action="append", default=[])
    _ = parser.add_argument("--allowed-registry", action="append", default=[])
    args = parser.parse_args()
    if args.apply and args.auto:
        parser.error("--apply and --auto are mutually exclusive")
    if args.auto and (args.expected_revision or args.expected_digest):
        parser.error("--auto does not accept --expected-revision or --expected-digest")
    if args.apply and not (args.expected_revision and args.expected_digest and args.actor_id):
        parser.error("--apply requires --expected-revision, --expected-digest and --actor-id")
    if args.auto and not args.actor_id:
        parser.error("--auto requires --actor-id")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
