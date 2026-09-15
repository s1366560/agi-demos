"""Explicit CAS maintenance through existing local development application APIs."""

import argparse
import asyncio
import json
import secrets
from pathlib import Path

from src.application.services.auth_service_v2 import AuthService
from src.application.services.root_builtin_bundle_upgrade_service_v2 import (
    upgrade_root_builtin_bundle_v2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    BootstrapLocalPlatformAdministrator,
)
from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, engine
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_local_platform_administrator_repository import (
    SqlLocalPlatformAdministratorRepository,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

OLD_DIGEST = "sha256:96da5799d83ad10bd2d1f673d5e3c1fed7b13402e4b7f7663dbb83a43c53165a"
SCOPES = (
    ScopeV2(kind=ScopeKindV2.ROOT),
    *(
        ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id="02f6fccc-0ac9-4729-bac7-38e77d1c61ef",
            project_id="738ace12-0d21-48ca-847d-cd0c2802816d",
            session_id=session_id,
        )
        for session_id in (
            "e9c68760-fc1c-55bd-8f87-cd4e1a884fcb",
            "c0d589a0-9f67-5c20-871e-f00c8bc756e2",
            "6032f5fb-4941-549f-ae2f-b87e5b34fa3c",
            "7e29b916-4c4a-4137-8bc4-e16274ff45d7",
        )
    ),
)


async def run(expected_target_digest: str, apply: bool) -> None:
    settings = get_settings()
    sources = production_bundle_sources_v2()
    replacement = sources.desired_set.bundles[0]
    if replacement.digest != expected_target_digest:
        raise ValueError("Current source differs from the reviewed target digest")
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=async_session_factory,
        production_sources=sources,
        trusted_public_keys=tuple(
            p.read_text() for p in settings.plugin_marketplace_trusted_key_files
        ),
        allowed_registries=frozenset(settings.plugin_marketplace_allowed_registries),
    )
    report = {"target_digest": replacement.digest, "applied": False, "scopes": []}
    async with async_session_factory() as session:
        repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
        heads = []
        for scope in SCOPES:
            head = await repository.current_desired_set(scope)
            if head is None:
                raise ValueError("Expected QA scope has no desired state")
            expected_revision = head.desired_set.revision
            old = next(b for b in head.desired_set.bundles if b.bundle_id == replacement.bundle_id)
            if old.digest != OLD_DIGEST:
                raise ValueError("Current builtin differs from the reviewed old digest")
            heads.append((scope, head, old))
            report["scopes"].append(
                {
                    "kind": scope.kind.value,
                    "session_id": scope.session_id,
                    "before_revision": expected_revision,
                    "before_digest": old.digest,
                }
            )
        if not apply:
            print(json.dumps(report))
            return
        bootstrap = BootstrapLocalPlatformAdministrator(
            repository=SqlLocalPlatformAdministratorRepository(session),
            hash_password=AuthService.get_password_hash,
            environment=settings.environment,
            database_host=settings.postgres_host,
            api_host="localhost",
        )
        identity = await bootstrap.execute(
            email=f"desktop-maintenance-{secrets.token_hex(8)}@localhost.invalid",
            password=secrets.token_urlsafe(48),
        )
        await session.commit()
        report["actor_id"] = identity.user_id
        try:
            for index, (scope, head, old) in enumerate(heads):
                updated = await upgrade_root_builtin_bundle_v2(
                    session,
                    sources=sources,
                    load_verified_bundle=loader,
                    expected_revision=head.desired_set.revision,
                    expected_bundle=old,
                    actor_id=identity.user_id,
                    scope=scope,
                )
                assert updated.desired_set.profile_source == head.desired_set.profile_source
                report["scopes"][index].update(
                    after_revision=updated.desired_set.revision,
                    profile_source_preserved=True,
                )
            await session.commit()
            report["applied"] = True
        finally:
            await session.rollback()
            await bootstrap.deactivate(identity)
            await session.commit()
            report["temporary_identity_deactivated"] = True
            Path(__file__).with_name("builtin-selection-maintenance-result.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
    print(json.dumps(report))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-target-digest", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        await run(args.expected_target_digest, args.apply)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        raise SystemExit(f"Maintenance failed ({type(error).__name__})") from None
