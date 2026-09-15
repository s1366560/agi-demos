"""Read-only final QA bundle recovery plan; never writes DB or calls mutation APIs."""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, engine
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    desired_bundle_set_v2_to_payload,
    parse_desired_bundle_set_v2,
)
from src.infrastructure.plugins.v2.scope import scope_v2_to_payload

TENANT = "02f6fccc-0ac9-4729-bac7-38e77d1c61ef"
PROJECT = "738ace12-0d21-48ca-847d-cd0c2802816d"
OWNER = "bf922bb7-290d-4252-8891-f82b97aa14b2"
OLD = "sha256:0577993e255866662231b36e6524bb194b233a57cc379038eb6882a7b3098014"
SESSIONS = (
    "e9c68760-fc1c-55bd-8f87-cd4e1a884fcb",
    "c0d589a0-9f67-5c20-871e-f00c8bc756e2",
    "6032f5fb-4941-549f-ae2f-b87e5b34fa3c",
    "7e29b916-4c4a-4137-8bc4-e16274ff45d7",
    "0687a537-5846-5e0b-9a02-e90b414db0fd",
)
REMOVE_FROM = frozenset(SESSIONS[2:4])
FIXTURE = {
    "bundle_id": "qa-marketplace-marker-bundle",
    "version": "1.0.0",
    "digest": "sha256:5690047548f07476e64db9b812514d7732d90fd4898f014634c1affef3637e18",
    "source": "marketplace://qa-marketplace-marker-bundle/1.0.0",
}


def scope_for(cid):
    return (
        ScopeV2(kind=ScopeKindV2.SESSION, tenant_id=TENANT, project_id=PROJECT, session_id=cid)
        if cid
        else ScopeV2(kind=ScopeKindV2.ROOT)
    )


def replacement_for(target):
    replacement = production_bundle_sources_v2().desired_set.bundles[0]
    if replacement.digest != target:
        raise ValueError("Current production artifact differs from reviewed target")
    return replacement


def candidate(current, cid, target):
    replacement = replacement_for(target)
    if desired_bundle_set_digest_v2(current) != current.digest:
        raise ValueError("Current desired digest is invalid")
    old = [b for b in current.bundles if b.bundle_id == replacement.bundle_id]
    if len(old) != 1 or (
        old[0].version != replacement.version
        or old[0].source != replacement.source
        or old[0].digest not in {OLD, target}
    ):
        raise ValueError("Unexpected baseline reference; stop for review")
    bundles = []
    removed = False
    for item in current.bundles:
        payload = {key: getattr(item, key) for key in FIXTURE}
        if cid in REMOVE_FROM and item.bundle_id == FIXTURE["bundle_id"]:
            if payload != FIXTURE:
                raise ValueError("Fixture identity differs from exact reviewed reference")
            removed = True
            continue
        bundles.append(replacement if item == old[0] else item)
    if tuple(bundles) == current.bundles:
        return None
    updated = replace(current, revision=current.revision + 1, bundles=tuple(bundles))
    updated = replace(updated, digest=desired_bundle_set_digest_v2(updated))
    assert updated.profile_source == current.profile_source
    assert parse_desired_bundle_set_v2(desired_bundle_set_v2_to_payload(updated)) == updated
    return {
        "scope": scope_v2_to_payload(scope_for(cid)),
        "before": desired_bundle_set_v2_to_payload(current),
        "fixture_removed": removed,
        "profile_source_preserved": True,
        "put_body": {
            "schema_version": 2,
            "scope": scope_v2_to_payload(scope_for(cid)),
            "expected_revision": current.revision,
            "desired_bundle_set": desired_bundle_set_v2_to_payload(updated),
        },
    }


async def prepare(target, output):
    replacement_for(target)
    rows = []
    async with async_session_factory() as db:
        repo = PlatformPluginDesiredBundleSetRepositoryV2(db)
        for cid in (None, *SESSIONS):
            scope = scope_for(cid)
            head = await repo.current_desired_set(scope)
            if head is None:
                raise ValueError("Expected QA desired state is missing")
            ref = head.desired_set.profile_source
            exact = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
                scope=scope, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
            )
            if exact is None:
                raise ValueError("Exact retained ProfileSource is unavailable")
            rows.append(candidate(head.desired_set, cid, target))
    report = {
        "applied": False,
        "target_digest": target,
        "scopes": rows,
        "order": [
            "Freeze and recheck reviewed production digest",
            "Authorized ROOT operator uses upgrade_root_builtin_bundle_v2 for ROOT only",
            "Restart new API; normal ROOT verification and publication must succeed",
            "Original owner fresh GET/PUT CAS for five QA sessions; never replay this plan blindly",
            "Normal session prepare verifies archives; no model or fallback in this maintenance",
        ],
    }
    Path(output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"applied": False, "target_digest": target, "scopes": len(rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-target-digest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    async def main():
        try:
            await prepare(args.expected_target_digest, args.output)
        finally:
            await engine.dispose()

    try:
        asyncio.run(main())
    except Exception as error:
        raise SystemExit(f"Read-only planning failed ({type(error).__name__})") from None
