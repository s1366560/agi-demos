#!/usr/bin/env python3
"""Execute paired SQLite/PostgreSQL Workspace authority scenarios."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_ROOT = REPO_ROOT / "third_party/avernet-bcs"
DEFAULT_ALLOWLIST = REPO_ROOT / "docs/architecture/workspace-core-cross-store-allowlist.json"

SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "mutation_commit_receipt_outbox",
        "sqliteFile": "crates/services/memstack-workspace-store/tests/sqlite_mutation_contract.rs",
        "sqliteTest": "successful_mutation_commits_domain_revision_receipt_and_outbox",
        "postgresFile": "crates/services/memstack-workspace-store/tests/postgres_mutation_contract.rs",
        "postgresTest": "postgres_commits_domain_revision_receipt_and_outbox",
    },
    {
        "id": "mutation_outbox_rollback",
        "sqliteFile": "crates/services/memstack-workspace-store/tests/sqlite_mutation_contract.rs",
        "sqliteTest": "outbox_failure_rolls_back_domain_revision_and_receipt",
        "postgresFile": "crates/services/memstack-workspace-store/tests/postgres_mutation_contract.rs",
        "postgresTest": "postgres_outbox_failure_rolls_back_every_prior_write",
    },
    {
        "id": "message_append_replay_rollback",
        "sqliteFile": "crates/services/memstack-workspace-store/tests/sqlite_message_contract.rs",
        "sqliteTest": "message_append_is_atomic_replayable_and_oldest_first",
        "postgresFile": "crates/services/memstack-workspace-store/tests/postgres_message_contract.rs",
        "postgresTest": "postgres_message_append_replay_mentions_and_rollback_contract",
    },
    {
        "id": "task_dispatch_fencing",
        "sqliteFile": "crates/services/memstack-workspace-service/tests/workspace_tasks.rs",
        "sqliteTest": "execution_task_assignment_and_recovery_enqueue_fenced_dispatches",
        "postgresFile": "crates/services/memstack-workspace-service/tests/postgres_task_authority.rs",
        "postgresTest": "postgres_task_authority_replays_dispatches_and_fences_provider_handoff",
    },
    {
        "id": "context_judge_cas_replay",
        "sqliteFile": "crates/services/memstack-workspace-service/tests/sqlite_context_contract.rs",
        "sqliteTest": "context_service_judges_ambiguity_and_commits_cas_replay_audit_and_outbox",
        "postgresFile": "crates/services/memstack-workspace-service/tests/postgres_context_contract.rs",
        "postgresTest": "postgres_context_jsonb_judge_cas_replay_audit_and_outbox_are_atomic",
    },
)


def _rust_function_names(path: Path) -> frozenset[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse("\n".join(f"def {name}(): pass" for name in _rust_function_tokens(source)))
    return frozenset(node.name for node in tree.body if isinstance(node, ast.FunctionDef))


def _rust_function_tokens(source: str) -> list[str]:
    names: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("async fn ") or stripped.startswith("fn "):
            token = stripped.removeprefix("async ").removeprefix("fn ").split("(", maxsplit=1)[0]
            if token.isidentifier():
                names.append(token)
    return names


def validate_scenarios(
    scenarios: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for scenario in scenarios:
        scenario_id = scenario["id"]
        if scenario_id in resolved:
            raise ValueError(f"duplicate cross-store scenario id: {scenario_id}")
        pair = {
            key: scenario[key]
            for key in ("sqliteFile", "sqliteTest", "postgresFile", "postgresTest")
        }
        for side in ("sqlite", "postgres"):
            path = RUST_ROOT / pair[f"{side}File"]
            function_name = pair[f"{side}Test"]
            if not path.is_file() or function_name not in _rust_function_names(path):
                raise ValueError(
                    f"cross-store scenario {scenario_id} is missing {function_name} in {path}"
                )
        resolved[scenario_id] = pair
    return resolved


def _cargo_target(file_path: str) -> tuple[str, str]:
    parts = Path(file_path).parts
    package = parts[2]
    test_target = Path(parts[-1]).stem
    return package, test_target


def _run_sqlite_scenarios(resolved: Mapping[str, Mapping[str, str]]) -> None:
    for pair in resolved.values():
        package, target = _cargo_target(pair["sqliteFile"])
        subprocess.run(
            ["cargo", "test", "-p", package, "--test", target, pair["sqliteTest"], "--locked"],
            cwd=RUST_ROOT,
            check=True,
        )


def _load_allowlist(path: Path) -> frozenset[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("allowlistVersion") != 1:
        raise ValueError("cross-store structure allowlist must use version 1")
    pointers = payload.get("ignoredJsonPointers")
    if not isinstance(pointers, list) or not all(
        isinstance(pointer, str) and pointer.startswith("/") for pointer in pointers
    ):
        raise ValueError("cross-store ignoredJsonPointers must be JSON pointers")
    if len(pointers) != len(set(pointers)):
        raise ValueError("cross-store ignoredJsonPointers contains duplicates")
    return frozenset(pointers)


def _remove_pointer(value: object, pointer: str) -> bool:
    if not isinstance(value, dict):
        return False
    segments = [
        segment.replace("~1", "/").replace("~0", "~")
        for segment in pointer.removeprefix("/").split("/")
    ]
    current: object = value
    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return isinstance(current, dict) and current.pop(segments[-1], None) is not None


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def compare_normalized_states(
    sqlite_state: Mapping[str, object],
    postgres_state: Mapping[str, object],
    *,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
) -> dict[str, str]:
    ignored_pointers = _load_allowlist(allowlist_path)
    sqlite_normalized = json.loads(json.dumps(sqlite_state))
    postgres_normalized = json.loads(json.dumps(postgres_state))
    used_pointers = {
        pointer
        for pointer in ignored_pointers
        if _remove_pointer(sqlite_normalized, pointer)
        or _remove_pointer(postgres_normalized, pointer)
    }
    stale_pointers = ignored_pointers - used_pointers
    if stale_pointers:
        raise ValueError(f"stale cross-store structure exemptions: {sorted(stale_pointers)}")

    sqlite_hash = _canonical_hash(sqlite_normalized)
    postgres_hash = _canonical_hash(postgres_normalized)
    if sqlite_hash != postgres_hash:
        raise ValueError(
            "normalized authority state hash mismatch: "
            f"sqlite={sqlite_hash}, postgres={postgres_hash}"
        )
    return {
        "sha256": sqlite_hash,
        "sqliteSha256": sqlite_hash,
        "postgresSha256": postgres_hash,
    }


def _run_paired_state_contract() -> dict[str, str]:
    handle, output_name = tempfile.mkstemp(prefix="workspace-cross-store-", suffix=".json")
    os.close(handle)
    output = Path(output_name)
    try:
        environment = os.environ.copy()
        environment["WORKSPACE_CROSS_STORE_STATE_OUTPUT"] = str(output)
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "scripts/avernet-bcs/verify-postgres-schema.py",
                "--cross-store-only",
            ],
            cwd=REPO_ROOT,
            env=environment,
            check=True,
        )
        states = json.loads(output.read_text(encoding="utf-8"))
        return compare_normalized_states(states["sqlite"], states["postgres"])
    finally:
        output.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declarations-only", action="store_true")
    args = parser.parse_args()

    resolved = validate_scenarios(SCENARIOS)
    if not args.declarations_only:
        _run_sqlite_scenarios(resolved)
        hash_result = _run_paired_state_contract()
        print(f"Workspace cross-store normalized authority hash passed ({hash_result['sha256']})")
    print(f"Workspace cross-store scenarios passed ({len(resolved)} declared pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
