"""The billing guest only receives a plan name and returns a storage allowance."""

import asyncio
import hashlib
import json
import re
from pathlib import Path

from src.configuration.config import get_settings
from src.infrastructure.plugins.v2.bundle_archive import MAX_BUNDLE_BYTES_V2
from src.infrastructure.plugins.wasm_host import WasmToolHost

_DEFAULT_GUEST_DIGEST = "67ff4d808ce6599bd060675a9c12489724298a621ff50fc609aef80de1a5b03f"
_ID = "memstack-billing"


class BillingInvalidPlanV2(ValueError):
    """The policy has no quote for the requested plan."""


def load_policy(archive_digest: object = None) -> WasmToolHost:
    limits = {
        "max_output_bytes": 1024,
        "memory_limit_bytes": 1024 * 1024,
        "fuel_budget": 1_000_000,
        "wall_time_ms": 200,
    }
    if archive_digest is None:
        guest = (Path(__file__).resolve().parents[1] / "quote.wasm").read_bytes()
        if hashlib.sha256(guest).hexdigest() != _DEFAULT_GUEST_DIGEST:
            raise ValueError("bundled billing policy digest mismatch")
    else:
        if not isinstance(archive_digest, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", archive_digest
        ):
            raise ValueError("billing policy requires a SHA-256 archive digest")
        settings = get_settings()
        directory = settings.billing_policy_archive_directory
        if directory is None:
            raise ValueError("billing policy archive directory is unavailable")
        archive = directory / (archive_digest.removeprefix("sha256:") + ".zip")
        with archive.open("rb") as source:
            raw = source.read(MAX_BUNDLE_BYTES_V2 + 1)
        if (
            len(raw) > MAX_BUNDLE_BYTES_V2
            or "sha256:" + hashlib.sha256(raw).hexdigest() != archive_digest
        ):
            raise ValueError("billing policy archive digest mismatch")
        from src.infrastructure.plugins.v2.project_plugin_package import admit_package

        # Only an operator pin can assign a signed release authority over tenant quotas.
        keys = tuple(path.read_text() for path in settings.plugin_marketplace_trusted_key_files)
        # The signed account UI can declare these tenant commands alongside the Wasm.
        # This resolver extracts only the import-free quote guest and never dispatches commands.
        package = admit_package(
            raw,
            keys,
            frozenset(
                {
                    "tools.execute",
                    "ui.slot",
                    "app.billing.account.read",
                    "app.billing.plan.write",
                }
            ),
            binding=None,
        )
        if package.plugin_id != _ID or not any(
            tool.name == "quote" and tool.abi == "invoke" for tool in package.contribution.tools
        ):
            raise ValueError("billing policy archive must provide the official quote operation")
        guest = package.wasm
        limits = {key: min(limit, package.quotas[key]) for key, limit in limits.items()}
    return WasmToolHost(
        _ID,
        guest,
        expected_abi="invoke",
        fuel_budget=limits["fuel_budget"],
        memory_limit_bytes=limits["memory_limit_bytes"],
        wall_time_ms=limits["wall_time_ms"],
        max_output_bytes=limits["max_output_bytes"],
    )


async def quote(host: WasmToolHost, plan: object, tenant_id: str) -> int:
    if not isinstance(plan, str) or not plan or len(plan) > 128:
        raise BillingInvalidPlanV2
    request = json.dumps({"plan": plan}, sort_keys=True, separators=(",", ":"))
    response = json.loads(
        await asyncio.to_thread(host.invoke_json, "quote", request, tenant_id=tenant_id)
    )
    if isinstance(response, dict) and response.get("error") == "unknown_plan":
        raise BillingInvalidPlanV2
    if (
        not isinstance(response, dict)
        or response.get("plan") != plan
        or type(limit := response.get("storage_limit")) is not int
        or not 0 <= limit < 2**63
    ):
        raise ValueError("invalid billing quote returned by the installed worker")
    return limit
