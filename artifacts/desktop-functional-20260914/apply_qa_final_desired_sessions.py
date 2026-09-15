"""Original-owner HTTP CAS recovery. Default is read-only; ROOT is never mutated."""

import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path

import httpx
from prepare_qa_final_desired_recovery import (
    OWNER,
    SESSIONS,
    candidate,
    replacement_for,
    scope_for,
)

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, engine
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.protocol import parse_desired_bundle_set_v2
from src.infrastructure.plugins.v2.scope import scope_v2_to_payload

ENDPOINT = "/api/v1/platform-plugins/v2/desired-bundle-sets/current"


async def run(args):
    replacement = replacement_for(args.expected_target_digest)
    # Read-only check; ROOT upgrade/publication is a separate authorized operator action.
    async with async_session_factory() as db:
        root = await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(
            scope_for(None)
        )
        if root is None or replacement not in root.desired_set.bundles:
            raise ValueError("ROOT must be formally upgraded before session recovery")
    report = {"apply_requested": args.apply, "target_digest": replacement.digest, "sessions": []}
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30) as client:
        health = await client.get("/health")
        health.raise_for_status()
        password = os.environ.get("QA_OWNER_PASSWORD") or getpass.getpass(
            "Original QA owner password: "
        )
        login = await client.post(
            "/api/v1/auth/token", data={"username": args.email, "password": password}
        )
        del password
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        try:
            me = await client.get("/api/v1/auth/me")
            me.raise_for_status()
            if me.json().get("user_id") != OWNER:
                raise ValueError("Authenticated identity is not the original QA owner")
            for cid in SESSIONS:
                scope = scope_v2_to_payload(scope_for(cid))
                params = {"scope_kind": scope.pop("kind"), **scope}
                response = await client.get(ENDPOINT, params=params)
                response.raise_for_status()
                body = response.json()
                if body["scope"] != scope_v2_to_payload(scope_for(cid)):
                    raise ValueError("GET returned a different scope")
                current = parse_desired_bundle_set_v2(body["desired_bundle_set"])
                plan = candidate(current, cid, args.expected_target_digest)
                if plan is None:
                    report["sessions"].append(
                        {"session_id": cid, "unchanged_revision": current.revision}
                    )
                    continue
                plan["applied"] = False
                report["sessions"].append(plan)
                if args.apply:
                    replacement_for(args.expected_target_digest)
                    put = await client.put(ENDPOINT, json=plan["put_body"])
                    put.raise_for_status()
                    after = await client.get(ENDPOINT, params=params)
                    after.raise_for_status()
                    if after.json()["desired_bundle_set"] != plan["put_body"]["desired_bundle_set"]:
                        raise ValueError("Post-CAS state differs; stop for review")
                    plan["after"] = after.json()["desired_bundle_set"]
                    plan["applied"] = True
        finally:
            logout = await client.post("/api/v1/auth/signout")
            report["owner_auth_revoked"] = logout.status_code == 200
            client.headers.pop("Authorization", None)
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"processed": len(report["sessions"]), "apply_requested": args.apply}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-target-digest", required=True)
    parser.add_argument("--email", required=True)
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
            f"Owner CAS failed ({type(error).__name__}); inspect the safe report"
        ) from None
