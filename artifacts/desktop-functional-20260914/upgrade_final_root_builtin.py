"""ROOT-only builtin maintenance. Dry-run by default; no session mutations."""

import argparse
import asyncio
import json
import secrets
from pathlib import Path

from prepare_qa_final_desired_recovery import OLD, replacement_for, scope_for

from src.application.services.auth_service_v2 import AuthService
from src.application.services.root_builtin_bundle_upgrade_service_v2 import (
    upgrade_root_builtin_bundle_v2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    BootstrapLocalPlatformAdministrator,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, engine
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_local_platform_administrator_repository import (
    SqlLocalPlatformAdministratorRepository,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import desired_bundle_set_v2_to_payload


def exact_baseline(current, replacement):
    matches = [item for item in current.bundles if item.bundle_id == replacement.bundle_id]
    if len(matches) != 1:
        raise ValueError("ROOT must have exactly one builtin baseline")
    old = matches[0]
    if (old.version, old.source) != (replacement.version, replacement.source):
        raise ValueError("ROOT baseline identity differs from reviewed source")
    if old.digest not in {OLD, replacement.digest}:
        raise ValueError("Unexpected ROOT builtin digest; stop for review")
    return old


async def run(args):
    replacement = replacement_for(args.expected_target_digest)
    sources = production_bundle_sources_v2()
    report = {"apply_requested": args.apply, "applied": False, "target_digest": replacement.digest}
    try:
        async with async_session_factory() as session:
            scope = scope_for(None)
            repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
            head = await repository.current_desired_set(scope)
            if head is None:
                raise ValueError("ROOT desired state is missing")
            before = head.desired_set
            old = exact_baseline(before, replacement)
            ref = before.profile_source
            source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
                scope=scope, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
            )
            if source is None:
                raise ValueError("Exact ROOT ProfileSource is unavailable")
            report["before"] = desired_bundle_set_v2_to_payload(before)
            report["expected_revision"] = before.revision
            report["already_current"] = old == replacement
            if old == replacement or not args.apply:
                return
            settings = get_settings()
            loader = ScopedInstalledBundleLoaderV2(
                session_factory=async_session_factory,
                production_sources=sources,
                trusted_public_keys=tuple(
                    path.read_text() for path in settings.plugin_marketplace_trusted_key_files
                ),
                allowed_registries=frozenset(settings.plugin_marketplace_allowed_registries),
            )
            bootstrap = BootstrapLocalPlatformAdministrator(
                repository=SqlLocalPlatformAdministratorRepository(session),
                hash_password=AuthService.get_password_hash,
                environment=settings.environment,
                database_host=settings.postgres_host,
                api_host="localhost",
            )
            identity = await bootstrap.execute(
                email=f"desktop-root-maintenance-{secrets.token_hex(8)}@localhost.invalid",
                password=secrets.token_urlsafe(48),
            )
            try:
                await session.commit()
                replacement_for(args.expected_target_digest)
                updated = await upgrade_root_builtin_bundle_v2(
                    session,
                    sources=sources,
                    load_verified_bundle=loader,
                    expected_revision=before.revision,
                    expected_bundle=old,
                    actor_id=identity.user_id,
                    scope=scope,
                )
                if updated.desired_set.profile_source != before.profile_source:
                    raise ValueError("ROOT ProfileSource changed unexpectedly")
                expected = tuple(replacement if item == old else item for item in before.bundles)
                if updated.desired_set.bundles != expected:
                    raise ValueError("ROOT changed bundles beyond exact builtin replacement")
                await session.commit()
                fresh = await repository.current_desired_set(scope)
                if fresh is None or fresh.desired_set != updated.desired_set:
                    raise ValueError("Post-CAS ROOT differs from committed target")
                report["after"] = desired_bundle_set_v2_to_payload(fresh.desired_set)
                report["profile_source_preserved"] = True
                report["applied"] = True
            finally:
                await session.rollback()
                await bootstrap.deactivate(identity)
                await session.commit()
                report["temporary_identity_deactivated"] = True
    finally:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {key: value for key, value in report.items() if key not in {"before", "after"}}
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-target-digest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    async def main():
        try:
            await run(args)
        finally:
            await engine.dispose()

    try:
        asyncio.run(main())
    except Exception as error:
        raise SystemExit(
            f"ROOT maintenance failed ({type(error).__name__}); inspect safe report"
        ) from None
