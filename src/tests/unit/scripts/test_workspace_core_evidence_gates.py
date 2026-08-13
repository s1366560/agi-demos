"""Contracts for executable Workspace implementation evidence gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import asyncpg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
POSTGRES_VERIFIER_PATH = REPO_ROOT / "scripts/avernet-bcs/verify-postgres-schema.py"
LEGACY_SENTINEL_PATH = REPO_ROOT / "scripts/workspace_core_legacy_sentinel.py"
EVENT_DELIVERY_PATH = REPO_ROOT / "scripts/workspace-core/verify-event-delivery.py"


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts/workspace-core" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_postgres_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_postgres_schema",
        POSTGRES_VERIFIER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_legacy_sentinel() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workspace_core_legacy_sentinel",
        LEGACY_SENTINEL_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_event_delivery() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_event_delivery",
        EVENT_DELIVERY_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_legacy_sentinel_covers_every_workspace_source_table() -> None:
    verifier = _load_postgres_verifier()

    assert verifier._LEGACY_WORKSPACE_TABLES == (
        "blackboard_files",
        "blackboard_posts",
        "blackboard_replies",
        "cyber_genes",
        "cyber_objectives",
        "topology_edges",
        "topology_nodes",
        "workspace_agent_policies",
        "workspace_agents",
        "workspace_blackboard_outbox",
        "workspace_collaboration_authorities",
        "workspace_collaboration_mutation_receipts",
        "workspace_deployments",
        "workspace_members",
        "workspace_messages",
        "workspace_pipeline_contracts",
        "workspace_pipeline_runs",
        "workspace_pipeline_stage_runs",
        "workspace_plan_blackboard_entries",
        "workspace_plan_events",
        "workspace_plan_nodes",
        "workspace_plan_outbox",
        "workspace_plans",
        "workspace_task_session_attempts",
        "workspace_tasks",
        "workspaces",
    )
    install_sql = verifier._legacy_workspace_write_sentinel_sql()
    assert "RAISE EXCEPTION 'legacy_workspace_write_forbidden'" in install_sql
    assert all(f'ON public."{table}"' in install_sql for table in verifier._LEGACY_WORKSPACE_TABLES)


def test_postgres_legacy_audit_rejects_any_scan_or_mutation_delta() -> None:
    verifier = _load_postgres_verifier()
    baseline = {
        table: {
            "seq_scan": 1,
            "idx_scan": 2,
            "n_tup_ins": 3,
            "n_tup_upd": 4,
            "n_tup_del": 5,
        }
        for table in verifier._LEGACY_WORKSPACE_TABLES
    }

    verifier._assert_legacy_workspace_stat_delta(baseline, dict(baseline))

    changed = {
        **baseline,
        "workspaces": {**baseline["workspaces"], "idx_scan": 3},
    }
    with pytest.raises(RuntimeError, match="legacy Workspace table activity detected"):
        verifier._assert_legacy_workspace_stat_delta(baseline, changed)


def test_postgres_legacy_sentinel_matches_stable_sqlstate_and_reason() -> None:
    sentinel = _load_legacy_sentinel()

    expected = asyncpg.ObjectNotInPrerequisiteStateError("legacy_workspace_write_forbidden")
    wrong_reason = asyncpg.ObjectNotInPrerequisiteStateError("another failure")
    wrong_state = asyncpg.RaiseError("legacy_workspace_write_forbidden")

    assert sentinel._is_write_sentinel_error(expected) is True
    assert sentinel._is_write_sentinel_error(wrong_reason) is False
    assert sentinel._is_write_sentinel_error(wrong_state) is False


def test_disposable_cleanup_requires_explicit_scope_zero_activity_and_confirmation() -> None:
    sentinel = _load_legacy_sentinel()
    zero_activity = {
        table: dict.fromkeys(sentinel.LEGACY_WORKSPACE_STAT_COLUMNS, 0)
        for table in sentinel.LEGACY_WORKSPACE_TABLES
    }

    sql = sentinel.protected_cleanup_sql(
        database_name="avernet_migrate_contract",
        application_name="workspace-core-disposable-cleanup",
        baseline=zero_activity,
        current=zero_activity,
        confirm="DROP_LEGACY_WORKSPACE_AUTHORITY",
    )

    assert "DROP TABLE IF EXISTS" in sql
    assert all(f'public."{table}"' in sql for table in sentinel.LEGACY_WORKSPACE_TABLES)
    assert "memstack_reject_legacy_workspace_write" in sql

    with pytest.raises(RuntimeError, match="disposable database"):
        sentinel.protected_cleanup_sql(
            database_name="memstack",
            application_name="workspace-core-disposable-cleanup",
            baseline=zero_activity,
            current=zero_activity,
            confirm="DROP_LEGACY_WORKSPACE_AUTHORITY",
        )
    with pytest.raises(RuntimeError, match="confirmation"):
        sentinel.protected_cleanup_sql(
            database_name="avernet_migrate_contract",
            application_name="workspace-core-disposable-cleanup",
            baseline=zero_activity,
            current=zero_activity,
            confirm="wrong",
        )

    activity = {
        **zero_activity,
        "workspaces": {**zero_activity["workspaces"], "seq_scan": 1},
    }
    with pytest.raises(RuntimeError, match="activity detected"):
        sentinel.protected_cleanup_sql(
            database_name="avernet_migrate_contract",
            application_name="workspace-core-disposable-cleanup",
            baseline=zero_activity,
            current=activity,
            confirm="DROP_LEGACY_WORKSPACE_AUTHORITY",
        )


@pytest.mark.unit
async def test_disposable_cleanup_executes_in_one_transaction_after_rechecking_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = _load_legacy_sentinel()
    zero_activity = {
        table: dict.fromkeys(sentinel.LEGACY_WORKSPACE_STAT_COLUMNS, 0)
        for table in sentinel.LEGACY_WORKSPACE_TABLES
    }

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.executed: list[str] = []
            self.closed = False

        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetchrow(self, _query: str) -> dict[str, str]:
            return {
                "database_name": "avernet_cleanup_contract",
                "application_name": "workspace-core-disposable-cleanup",
            }

        async def execute(self, query: str) -> None:
            self.executed.append(query)

        async def close(self) -> None:
            self.closed = True

    connection = FakeConnection()

    async def fake_connect(
        _dsn: str,
        *,
        server_settings: dict[str, str],
    ) -> FakeConnection:
        assert server_settings == {"application_name": "workspace-core-disposable-cleanup"}
        return connection

    async def fake_stats(_dsn: str) -> dict[str, dict[str, int]]:
        return zero_activity

    monkeypatch.setattr(sentinel.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(sentinel, "workspace_stats", fake_stats)

    await sentinel.cleanup_disposable_legacy_workspace_tables(
        "postgresql://isolated.invalid/avernet_cleanup_contract",
        baseline=zero_activity,
        confirm="DROP_LEGACY_WORKSPACE_AUTHORITY",
    )

    assert len(connection.executed) == 1
    assert "DROP TABLE IF EXISTS" in connection.executed[0]
    assert connection.closed is True


@pytest.mark.unit
async def test_disposable_cleanup_verifies_every_legacy_object_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = _load_legacy_sentinel()

    class FakeConnection:
        def __init__(self, results: list[list[dict[str, str]]]) -> None:
            self.results = results
            self.closed = False

        async def fetch(self, _query: str, *_args: object) -> list[dict[str, str]]:
            return self.results.pop(0)

        async def close(self) -> None:
            self.closed = True

    clean_connection = FakeConnection([[], [], []])

    async def connect_clean(_dsn: str) -> FakeConnection:
        return clean_connection

    monkeypatch.setattr(sentinel.asyncpg, "connect", connect_clean)
    await sentinel.assert_legacy_workspace_objects_removed("postgresql://isolated.invalid/clean")
    assert clean_connection.closed is True

    dirty_connection = FakeConnection([[{"relname": "workspaces"}], [], []])

    async def connect_dirty(_dsn: str) -> FakeConnection:
        return dirty_connection

    monkeypatch.setattr(sentinel.asyncpg, "connect", connect_dirty)
    with pytest.raises(RuntimeError, match="legacy Workspace cleanup left objects"):
        await sentinel.assert_legacy_workspace_objects_removed(
            "postgresql://isolated.invalid/dirty"
        )
    assert dirty_connection.closed is True


def test_evidence_attestation_requires_every_suite_to_execute_and_pass() -> None:
    verifier = _load_script("verify-implementation-evidence.py")
    evidence: dict[str, Any] = {
        "sourceRevision": f"sha256:{'d' * 64}",
        "schemaRevision": "head-1",
        "sourcesSha256": "a" * 64,
        "suites": [{"id": "one"}, {"id": "two"}],
    }

    incomplete = verifier.build_attestation(
        evidence,
        [{"id": "one", "passed": True, "exitCode": 0}],
        source_sha256="d" * 64,
        source_revision=f"sha256:{'d' * 64}",
        route_contract_sha256="b" * 64,
        implemented_route_keys_sha256="c" * 64,
    )
    failed = verifier.build_attestation(
        evidence,
        [
            {"id": "one", "passed": True, "exitCode": 0},
            {"id": "two", "passed": False, "exitCode": 1},
        ],
        source_sha256="d" * 64,
        source_revision=f"sha256:{'d' * 64}",
        route_contract_sha256="b" * 64,
        implemented_route_keys_sha256="c" * 64,
    )
    passed = verifier.build_attestation(
        evidence,
        [
            {"id": "one", "passed": True, "exitCode": 0},
            {"id": "two", "passed": True, "exitCode": 0},
        ],
        source_sha256="d" * 64,
        source_revision=f"sha256:{'d' * 64}",
        route_contract_sha256="b" * 64,
        implemented_route_keys_sha256="c" * 64,
    )

    assert incomplete["passed"] is False
    assert failed["passed"] is False
    assert passed["passed"] is True
    assert passed["schemaRevision"] == "head-1"
    assert passed["evidenceSourcesSha256"] == "a" * 64
    assert passed["routeContractSha256"] == "b" * 64
    assert passed["implementedRouteKeysSha256"] == "c" * 64
    assert passed["attestationVersion"] == 2
    assert passed["sourceSha256"] == "d" * 64
    assert passed["sourceRevision"] == f"sha256:{'d' * 64}"


def test_evidence_runner_rejects_unknown_suite_ids() -> None:
    verifier = _load_script("verify-implementation-evidence.py")
    evidence = {"suites": [{"id": "known", "command": "true"}]}

    with pytest.raises(ValueError, match="unknown evidence suite ids"):
        verifier.run_evidence_suites(evidence, selected_suite_ids=frozenset({"missing"}))


def test_evidence_runner_executes_all_commands_in_a_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _load_script("verify-implementation-evidence.py")
    commands: list[list[str]] = []

    class Completed:
        returncode = 0

    def run(command: list[str], **_kwargs: Any) -> Completed:
        commands.append(command)
        return Completed()

    monkeypatch.setattr(verifier.subprocess, "run", run)
    evidence = {"suites": [{"id": "migration", "command": "first && second"}]}

    results = verifier.run_evidence_suites(evidence)

    assert commands == [["/bin/sh", "-eu", "-c", "first && second"]]
    assert results == [
        {
            "id": "migration",
            "command": "first && second",
            "exitCode": 0,
            "passed": True,
        }
    ]


def test_event_delivery_runner_executes_the_ignored_redis_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_event_delivery()
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], **kwargs: Any) -> None:
        calls.append((command, kwargs["env"]))

    monkeypatch.setattr(verifier.subprocess, "run", run)

    verifier.run_delivery_contract(6380, repo_root=REPO_ROOT)

    assert calls[0][0] == [
        "scripts/avernet-bcs/cargo.sh",
        "test",
        "-p",
        "memstack-workspace-core",
        "--test",
        "plan_update_outbox_delivery",
        "--locked",
        "workspace_plan_updated_outbox_publishes_consumer_once_and_replays_after_crash",
        "--",
        "--ignored",
        "--exact",
        "--test-threads=1",
    ]
    assert calls[0][1]["BCS_TEST_REDIS_PORT"] == "6380"


def test_evidence_attestation_rejects_source_revision_drift() -> None:
    verifier = _load_script("verify-implementation-evidence.py")
    evidence: dict[str, Any] = {
        "sourceRevision": f"sha256:{'d' * 64}",
        "schemaRevision": "head-1",
        "sourcesSha256": "a" * 64,
        "suites": [{"id": "one"}],
    }

    with pytest.raises(ValueError, match="attestation source revision drifted"):
        verifier.build_attestation(
            evidence,
            [{"id": "one", "passed": True, "exitCode": 0}],
            source_sha256="d" * 64,
            source_revision="0" * 40,
            route_contract_sha256="b" * 64,
            implemented_route_keys_sha256="c" * 64,
        )


def test_selected_evidence_attestation_requires_only_selected_suites() -> None:
    verifier = _load_script("verify-implementation-evidence.py")
    evidence: dict[str, Any] = {
        "sourceRevision": f"sha256:{'d' * 64}",
        "schemaRevision": "head-1",
        "sourcesSha256": "a" * 64,
        "suites": [{"id": "one"}, {"id": "two"}],
    }

    attestation = verifier.build_attestation(
        evidence,
        [{"id": "one", "passed": True, "exitCode": 0}],
        source_sha256="d" * 64,
        source_revision=f"sha256:{'d' * 64}",
        route_contract_sha256="b" * 64,
        implemented_route_keys_sha256="c" * 64,
        expected_suite_ids=frozenset({"one"}),
    )

    assert attestation["passed"] is True
    assert attestation["suiteCount"] == 1
    assert attestation["completedSuiteCount"] == 1


def test_legacy_workspace_reference_gate_accepts_current_retired_runtime_surface() -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    allowlist = guard.load_allowlist(guard.DEFAULT_ALLOWLIST)

    guard.validate_allowlist(guard.scan_legacy_references(), allowlist)


def test_legacy_workspace_reference_allowlist_accepts_only_exact_offline_exemptions() -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    allowlist = {
        "offline_import": {
            "src/infrastructure/workspace_core/migration/importer.py": frozenset({"WorkspaceModel"})
        },
        "verification": {},
        "reverse_export": {},
    }

    guard.validate_allowlist(
        {"src/infrastructure/workspace_core/migration/importer.py": frozenset({"WorkspaceModel"})},
        allowlist,
    )

    with pytest.raises(ValueError, match="runtime=.*WorkspaceMemberModel"):
        guard.validate_allowlist(
            {
                "src/infrastructure/workspace_core/migration/importer.py": frozenset(
                    {"WorkspaceModel", "WorkspaceMemberModel"}
                )
            },
            allowlist,
        )
    with pytest.raises(ValueError, match="stale_exemptions=.*WorkspaceModel"):
        guard.validate_allowlist(
            {},
            allowlist,
        )


def test_legacy_workspace_allowlist_accepts_only_desktop_offline_import_tables(
    tmp_path: Path,
) -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        '{"allowlistVersion":2,"categories":{'
        '"offline_import":{'
        '"agi-stack/apps/desktop/sidecar/src/workspace_core_legacy_import.rs":'
        '["desktop_workspace_messages","desktop_workspaces"]},'
        '"verification":{},"reverse_export":{}}}',
        encoding="utf-8",
    )

    allowlist = guard.load_allowlist(allowlist_path)
    guard.validate_allowlist(
        {
            "agi-stack/apps/desktop/sidecar/src/workspace_core_legacy_import.rs": frozenset(
                {"desktop_workspace_messages", "desktop_workspaces"}
            )
        },
        allowlist,
    )

    with pytest.raises(ValueError, match="runtime=.*desktop_workspaces"):
        guard.validate_allowlist(
            {
                "agi-stack/apps/desktop/sidecar/src/local_runtime/session_store.rs": frozenset(
                    {"desktop_workspaces"}
                ),
                "agi-stack/apps/desktop/sidecar/src/workspace_core_legacy_import.rs": frozenset(
                    {"desktop_workspace_messages", "desktop_workspaces"}
                ),
            },
            allowlist,
        )


def test_legacy_workspace_allowlist_rejects_runtime_paths_and_missing_categories(
    tmp_path: Path,
) -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    invalid_runtime = tmp_path / "runtime.json"
    invalid_runtime.write_text(
        '{"allowlistVersion":2,"categories":{'
        '"offline_import":{"src/infrastructure/adapters/primary/web/runtime.py":'
        '["WorkspaceModel"]},"verification":{},"reverse_export":{}}}',
        encoding="utf-8",
    )
    missing_category = tmp_path / "missing.json"
    missing_category.write_text(
        '{"allowlistVersion":2,"categories":{"offline_import":{},"verification":{}}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="path is invalid for offline_import"):
        guard.load_allowlist(invalid_runtime)
    with pytest.raises(ValueError, match="must declare exactly"):
        guard.load_allowlist(missing_category)


def test_legacy_workspace_reference_scanner_cannot_be_bypassed_with_aliases(
    tmp_path: Path,
) -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    runtime = tmp_path / "src" / "runtime.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        "from models import WorkspaceModel as CurrentWorkspace\n"
        "import models\n"
        "first = CurrentWorkspace\n"
        "second = models.WorkspaceMemberModel\n",
        encoding="utf-8",
    )

    assert guard.scan_legacy_references(tmp_path) == {
        "src/runtime.py": frozenset({"WorkspaceModel", "WorkspaceMemberModel"})
    }


def test_legacy_workspace_reference_scanner_covers_every_retired_python_table_family(
    tmp_path: Path,
) -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    runtime = tmp_path / "src" / "runtime.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        "from models import (\n"
        "    BlackboardPostModel, CyberGeneModel, TopologyNodeModel,\n"
        "    WorkspaceBlackboardOutboxModel, WorkspaceDeploymentModel,\n"
        "    WorkspacePipelineRunModel, WorkspacePlanEventModel,\n"
        "    WorkspaceTaskSessionAttemptModel,\n"
        ")\n"
        "from persistence.sql_blackboard_repository import SqlBlackboardRepository\n"
        "from persistence.sql_cyber_gene_repository import SqlCyberGeneRepository\n"
        "from persistence.sql_topology_repository import SqlTopologyRepository\n",
        encoding="utf-8",
    )

    assert guard.scan_legacy_references(tmp_path) == {
        "src/runtime.py": frozenset(
            {
                "BlackboardPostModel",
                "CyberGeneModel",
                "SqlBlackboardRepository",
                "SqlCyberGeneRepository",
                "SqlTopologyRepository",
                "TopologyNodeModel",
                "WorkspaceBlackboardOutboxModel",
                "WorkspaceDeploymentModel",
                "WorkspacePipelineRunModel",
                "WorkspacePlanEventModel",
                "WorkspaceTaskSessionAttemptModel",
                "sql_blackboard_repository",
                "sql_cyber_gene_repository",
                "sql_topology_repository",
            }
        )
    }


def test_legacy_workspace_reference_scanner_covers_cross_language_runtime_surfaces(
    tmp_path: Path,
) -> None:
    guard = _load_script("verify-legacy-workspace-references.py")
    python_runtime = tmp_path / "src" / "runtime.py"
    server_runtime = tmp_path / "agi-stack" / "apps" / "server" / "src" / "main.rs"
    desktop_runtime = (
        tmp_path
        / "agi-stack"
        / "apps"
        / "desktop"
        / "sidecar"
        / "src"
        / "local_runtime"
        / "session_store.rs"
    )
    python_runtime.parent.mkdir(parents=True)
    server_runtime.parent.mkdir(parents=True)
    desktop_runtime.parent.mkdir(parents=True)
    python_runtime.write_text(
        "from persistence.sql_workspace_repository import "
        "SqlWorkspaceRepository as LegacyRepository\n",
        encoding="utf-8",
    )
    server_runtime.write_text(
        "mod workspace_api;\nuse crate::workspace_outbox_worker::start_workspace_outbox_worker;\n",
        encoding="utf-8",
    )
    desktop_runtime.write_text(
        'const LEGACY_QUERY: &str = "SELECT * FROM desktop_workspaces";\n',
        encoding="utf-8",
    )

    references = guard.scan_legacy_references(tmp_path)

    assert references["src/runtime.py"] == frozenset(
        {"SqlWorkspaceRepository", "sql_workspace_repository"}
    )
    assert references["agi-stack/apps/server/src/main.rs"] == frozenset(
        {"mod workspace_api", "workspace_api", "workspace_outbox_worker"}
    )
    assert references[
        "agi-stack/apps/desktop/sidecar/src/local_runtime/session_store.rs"
    ] == frozenset({"desktop_workspaces"})


def test_cross_store_scenarios_resolve_to_paired_sqlite_and_postgres_tests() -> None:
    verifier = _load_script("verify-cross-store-scenarios.py")

    resolved = verifier.validate_scenarios(verifier.SCENARIOS)

    assert set(resolved) == {
        "context_judge_cas_replay",
        "message_append_replay_rollback",
        "mutation_commit_receipt_outbox",
        "mutation_outbox_rollback",
        "task_dispatch_fencing",
    }
    assert all(pair["sqliteTest"] and pair["postgresTest"] for pair in resolved.values())


def test_cross_store_scenario_validation_rejects_missing_test_function() -> None:
    verifier = _load_script("verify-cross-store-scenarios.py")
    scenario = dict(verifier.SCENARIOS[0])
    scenario["postgresTest"] = "missing_postgres_contract"

    with pytest.raises(ValueError, match="missing_postgres_contract"):
        verifier.validate_scenarios((scenario,))


def test_cross_store_hash_requires_identical_normalized_authority_state(
    tmp_path: Path,
) -> None:
    verifier = _load_script("verify-cross-store-scenarios.py")
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        '{"allowlistVersion":1,"ignoredJsonPointers":[]}',
        encoding="utf-8",
    )
    sqlite_state = {
        "contractVersion": 1,
        "commit": {"revisionDelta": 1, "receiptCount": 1, "outboxCount": 1},
        "crashReplay": {"replayed": True, "receiptStable": True},
        "rollback": {"revisionDelta": 0, "receiptCount": 0, "outboxCount": 0},
    }

    result = verifier.compare_normalized_states(
        sqlite_state,
        dict(sqlite_state),
        allowlist_path=allowlist,
    )

    assert len(result["sha256"]) == 64
    assert result["sqliteSha256"] == result["postgresSha256"] == result["sha256"]

    postgres_state = dict(sqlite_state)
    postgres_state["rollback"] = {
        "revisionDelta": 1,
        "receiptCount": 0,
        "outboxCount": 0,
    }
    with pytest.raises(ValueError, match="normalized authority state hash mismatch"):
        verifier.compare_normalized_states(
            sqlite_state,
            postgres_state,
            allowlist_path=allowlist,
        )


def test_cross_store_structure_allowlist_is_explicit_and_rejects_stale_paths(
    tmp_path: Path,
) -> None:
    verifier = _load_script("verify-cross-store-scenarios.py")
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        '{"allowlistVersion":1,"ignoredJsonPointers":["/storageOnly"]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stale cross-store structure exemptions"):
        verifier.compare_normalized_states(
            {"contractVersion": 1},
            {"contractVersion": 1},
            allowlist_path=allowlist,
        )
