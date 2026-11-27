"""Build the billing Wasm guest and signed pages, commands, and quote operation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from wasmtime import wat2wasm

ROOT = Path(__file__).resolve().parent
PLUGIN = "memstack-billing"
PLAN_PLUGIN = "memstack-billing-plans"
PLAN_SERVICE = {"service": "service:package:memstack-billing-plans:quote", "version": "1.0.0"}


def compile_guest(plans: dict[str, int]) -> bytes:
    if not plans or any(
        not plan.isascii()
        or not plan.isalnum()
        or len(plan) > 32
        or type(limit) is not int
        or not 0 <= limit < 2**63
        for plan, limit in plans.items()
    ):
        raise ValueError("expected plan identifiers and nonnegative 64-bit quotas")
    data = []
    cursor = 2 * 65536

    def store(value: dict[str, object]) -> tuple[int, int]:
        nonlocal cursor
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        start = cursor
        cursor += len(raw)
        if cursor > 3 * 65536:
            raise ValueError("plan catalog exceeds guest memory")
        escaped = "".join(f"\\{byte:02x}" for byte in raw)
        data.append(f'(data (i32.const {start}) "{escaped}")')
        return start, len(raw)

    def reply(value: dict[str, object]) -> str:
        pos, size = store(value)
        return (
            f"(memory.copy (i32.const 65536) (i32.const {pos}) (i32.const {size})) "
            f"(return (i32.const {size}))"
        )

    cases = []
    for plan, limit in sorted(plans.items()):
        pos, size = store({"plan": plan})
        response = reply({"plan": plan, "storage_limit": limit})
        cases.append(
            f"(if (call $matches (local.get $length) (i32.const {pos}) (i32.const {size})) "
            f"(then {response}))"
        )
    unknown = reply({"error": "unknown_plan"})
    source = (
        (ROOT / "quote.wat.in")
        .read_text()
        .format(data="\n".join(data), cases="\n".join(cases), unknown=unknown)
    )
    return bytes(wat2wasm(source))


def build_release(
    plans: dict[str, int],
    *,
    version: str,
    signer: Ed25519PrivateKey,
    worker_image: str | None = None,
    plan_service: bool = False,
) -> bytes:
    from memstack_plugin_sdk.pack import build, stage_contribution

    with tempfile.TemporaryDirectory() as path:
        root = Path(path)
        spec = json.loads((ROOT / "package.json").read_bytes())
        executable = {"wasm": spec.pop("wasm")}
        if worker_image:
            executable = {"worker": "worker.json"}
            (root / "worker.json").write_text(
                json.dumps(
                    {
                        "schema": "memstack.mcp-oci-worker/1",
                        "image": worker_image,
                        "entrypoint": "/app/invoice-worker-with-plan-service"
                        if plan_service
                        else "/app/invoice-worker",
                    }
                )
            )
        else:
            (root / "quote.wasm").write_bytes(compile_guest(plans))
        permissions = ["tools.execute"]
        commands: list[dict[str, object]] = [
            {
                "id": f"quote-{plan}",
                "tool": "quote",
                "permissions": permissions,
                "payload": {"plan": plan},
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
            for plan in plans
        ]
        if worker_image:
            commands.extend(
                [
                    {
                        "id": "list-invoices",
                        "tool": "invoice.list",
                        "payload": {"limit": 16},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "permissions": ["tools.execute", "storage.read"],
                    },
                    {
                        "id": "create-invoice",
                        "tool": "invoice.create",
                        "payload": {},
                        "accepts_input": True,
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "permissions": ["tools.execute", "storage.read", "storage.write"],
                    },
                ]
            )
        actions = [
            {"id": f"quote-{plan}", "label": f"{plan.title()} storage allowance"} for plan in plans
        ]
        if worker_image:
            actions.append({"id": "list-invoices", "label": "View project invoices"})
        contribution = json.loads((ROOT / spec["contribution"]).read_bytes())
        stage_contribution(ROOT, root, spec["contribution"])
        contribution["commands"] = commands + [
            command for command in contribution["commands"] if "host_operation" in command
        ]
        for package_page in (p for p in contribution["pages"] if p["id"] == "account"):
            package_page["commands"] = [command["id"] for command in contribution["commands"]]
        contribution["tools"][0]["input_schema"]["properties"]["plan"]["enum"] = list(plans)
        page_path = Path(contribution["ui"][0]["path"])
        page_spec = json.loads((ROOT / page_path).read_bytes())
        page = json.dumps({**page_spec, "actions": actions}, separators=(",", ":")).encode()
        (root / page_path).parent.mkdir(parents=True, exist_ok=True)
        (root / page_path).write_bytes(page)
        contribution["ui"][0]["digest"] = "sha256:" + hashlib.sha256(page).hexdigest()
        if worker_image:
            if TYPE_CHECKING or __package__:
                from .workers.invoice_contract import contribution as worker_contribution
            else:
                from workers.invoice_contract import contribution as worker_contribution

            contribution.update(worker_contribution(plans))
        services = {}
        plugin_id = PLUGIN
        if plan_service:
            quote = contribution["tools"][0]
            if worker_image:
                services["requires"] = [{"alias": "plans", **PLAN_SERVICE}]
                quote["permissions"] = ["tools.execute", "services.call"]
                quote["service_aliases"] = ["plans"]
            else:
                plugin_id = PLAN_PLUGIN
                services["provides"] = [PLAN_SERVICE]
                quote["permissions"] = ["tools.execute", "services.provide"]
                contribution = {"schema": contribution["schema"], "tools": [quote]}
        (root / "contributions.json").write_text(json.dumps(contribution))
        config = root / "package.json"
        config.write_text(
            json.dumps(
                {
                    **spec,
                    "plugin_id": plugin_id,
                    "services": services,
                    "version": version,
                    **executable,
                }
            )
        )
        return build(config, signer)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, default=ROOT / "plans.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version")
    parser.add_argument("--key", type=Path)
    parser.add_argument(
        "--worker-image", help="immutable OCI image reference for the invoice worker"
    )
    parser.add_argument(
        "--plan-service",
        action="store_true",
        help="export signed plan quotes from Wasm or consume them from the OCI invoice worker",
    )
    args = parser.parse_args()
    plans = json.loads(args.plans.read_text())
    if args.version or args.key or args.worker_image or args.plan_service:
        if not args.version or not args.key:
            parser.error("a signed release requires both --version and --key")
        key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            parser.error("expected an Ed25519 signer")
        data = build_release(
            plans,
            version=args.version,
            signer=key,
            worker_image=args.worker_image,
            plan_service=args.plan_service,
        )
    else:
        data = compile_guest(plans)
    args.out.write_bytes(data)


if __name__ == "__main__":
    main()
