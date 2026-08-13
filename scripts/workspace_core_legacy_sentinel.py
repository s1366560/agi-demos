"""Isolated PostgreSQL guardrails for retired Workspace source tables."""

from __future__ import annotations

import re

import asyncpg

LEGACY_WORKSPACE_TABLES: tuple[str, ...] = (
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
LEGACY_WORKSPACE_STAT_COLUMNS = (
    "seq_scan",
    "idx_scan",
    "n_tup_ins",
    "n_tup_upd",
    "n_tup_del",
)
DISPOSABLE_DATABASE_PATTERN = re.compile(
    r"^(?:avernet_(?:migrate|schema|cross_store|cleanup)|memstack_(?:test|qa|cleanup))_[a-z0-9_]+$"
)
DISPOSABLE_CLEANUP_APPLICATION = "workspace-core-disposable-cleanup"
DISPOSABLE_CLEANUP_CONFIRMATION = "DROP_LEGACY_WORKSPACE_AUTHORITY"


def write_sentinel_sql() -> str:
    triggers = "\n".join(
        f'DROP TRIGGER IF EXISTS trg_memstack_legacy_workspace_write_sentinel ON public."{table}";\n'
        f"CREATE TRIGGER trg_memstack_legacy_workspace_write_sentinel "
        f'BEFORE INSERT OR UPDATE OR DELETE ON public."{table}" '
        "FOR EACH STATEMENT EXECUTE FUNCTION public.memstack_reject_legacy_workspace_write();"
        for table in LEGACY_WORKSPACE_TABLES
    )
    return (
        "CREATE OR REPLACE FUNCTION public.memstack_reject_legacy_workspace_write()\n"
        "RETURNS trigger LANGUAGE plpgsql AS $$\n"
        "BEGIN\n"
        "  RAISE EXCEPTION 'legacy_workspace_write_forbidden' USING ERRCODE = '55000';\n"
        "END;\n"
        "$$;\n"
        f"{triggers}"
    )


async def install_write_sentinel(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        existing_tables: set[str] = {
            str(row["tablename"])
            for row in await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename = ANY($1::text[])",
                list(LEGACY_WORKSPACE_TABLES),
            )
        }
        missing = set(LEGACY_WORKSPACE_TABLES).difference(existing_tables)
        if missing:
            raise RuntimeError(f"legacy Workspace sentinel tables are missing: {sorted(missing)}")
        await connection.execute(write_sentinel_sql())
    finally:
        await connection.close()


async def remove_write_sentinel(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        existing_tables = {
            str(row["tablename"])
            for row in await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename = ANY($1::text[])",
                list(LEGACY_WORKSPACE_TABLES),
            )
        }
        for table in sorted(existing_tables):
            await connection.execute(
                "DROP TRIGGER IF EXISTS trg_memstack_legacy_workspace_write_sentinel "
                f'ON public."{table}"'
            )
        await connection.execute(
            "DROP FUNCTION IF EXISTS public.memstack_reject_legacy_workspace_write()"
        )
    finally:
        await connection.close()


async def workspace_stats(test_dsn: str) -> dict[str, dict[str, int]]:
    connection = await asyncpg.connect(test_dsn)
    try:
        await connection.execute("SELECT pg_stat_clear_snapshot()")
        rows = await connection.fetch(
            "SELECT relname, seq_scan, idx_scan, n_tup_ins, n_tup_upd, n_tup_del "
            "FROM pg_stat_user_tables WHERE schemaname = 'public' "
            "AND relname = ANY($1::text[]) ORDER BY relname",
            list(LEGACY_WORKSPACE_TABLES),
        )
        return {
            str(row["relname"]): {
                column: int(row[column] or 0) for column in LEGACY_WORKSPACE_STAT_COLUMNS
            }
            for row in rows
        }
    finally:
        await connection.close()


def assert_zero_stat_delta(
    baseline: dict[str, dict[str, int]],
    current: dict[str, dict[str, int]],
) -> None:
    if set(baseline) != set(LEGACY_WORKSPACE_TABLES) or set(current) != set(
        LEGACY_WORKSPACE_TABLES
    ):
        raise RuntimeError("legacy Workspace table statistics are incomplete")
    deltas = {
        table: {
            column: current[table][column] - values[column]
            for column in LEGACY_WORKSPACE_STAT_COLUMNS
            if current[table][column] - values[column] != 0
        }
        for table, values in baseline.items()
    }
    activity = {table: values for table, values in deltas.items() if values}
    if activity:
        raise RuntimeError(f"legacy Workspace table activity detected: {activity}")


def protected_cleanup_sql(
    *,
    database_name: str,
    application_name: str,
    baseline: dict[str, dict[str, int]],
    current: dict[str, dict[str, int]],
    confirm: str,
) -> str:
    """Build the irreversible cleanup only after an isolated zero-activity proof."""
    if DISPOSABLE_DATABASE_PATTERN.fullmatch(database_name) is None:
        raise RuntimeError("legacy Workspace cleanup requires a disposable database")
    if application_name != DISPOSABLE_CLEANUP_APPLICATION:
        raise RuntimeError("legacy Workspace cleanup requires the isolated application name")
    if confirm != DISPOSABLE_CLEANUP_CONFIRMATION:
        raise RuntimeError("legacy Workspace cleanup confirmation is missing")
    assert_zero_stat_delta(baseline, current)

    # CASCADE is confined to the enumerated disposable legacy graph. The normal Alembic upgrade
    # path never executes this SQL; release cleanup remains a separate operator-controlled step.
    tables = ",\n    ".join(f'public."{table}"' for table in LEGACY_WORKSPACE_TABLES)
    return (
        "SET LOCAL lock_timeout = '10s';\n"
        f"DROP TABLE IF EXISTS\n    {tables}\nCASCADE;\n"
        "DROP FUNCTION IF EXISTS public.memstack_reject_legacy_workspace_write();\n"
    )


async def cleanup_disposable_legacy_workspace_tables(
    test_dsn: str,
    *,
    baseline: dict[str, dict[str, int]],
    confirm: str,
) -> None:
    """Irreversibly remove the retired schema from one verified disposable database."""
    current = await workspace_stats(test_dsn)
    connection = await asyncpg.connect(
        test_dsn,
        server_settings={"application_name": DISPOSABLE_CLEANUP_APPLICATION},
    )
    try:
        identity = await connection.fetchrow(
            "SELECT current_database() AS database_name, "
            "current_setting('application_name') AS application_name"
        )
        if identity is None:
            raise RuntimeError("cannot resolve disposable cleanup database identity")
        sql = protected_cleanup_sql(
            database_name=str(identity["database_name"]),
            application_name=str(identity["application_name"]),
            baseline=baseline,
            current=current,
            confirm=confirm,
        )
        async with connection.transaction():
            await connection.execute(sql)
    finally:
        await connection.close()


async def assert_legacy_workspace_objects_removed(test_dsn: str) -> None:
    """Prove the disposable cleanup removed tables and their sentinel objects."""
    connection = await asyncpg.connect(test_dsn)
    try:
        tables = await connection.fetch(
            "SELECT c.relname FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
            "AND c.relname = ANY($1::text[]) ORDER BY c.relname",
            list(LEGACY_WORKSPACE_TABLES),
        )
        triggers = await connection.fetch(
            "SELECT tgname FROM pg_trigger "
            "WHERE NOT tgisinternal "
            "AND tgname = 'trg_memstack_legacy_workspace_write_sentinel'"
        )
        functions = await connection.fetch(
            "SELECT p.proname FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' "
            "AND p.proname = 'memstack_reject_legacy_workspace_write'"
        )
        remaining = {
            "tables": [str(row["relname"]) for row in tables],
            "triggers": [str(row["tgname"]) for row in triggers],
            "functions": [str(row["proname"]) for row in functions],
        }
        if any(remaining.values()):
            raise RuntimeError(f"legacy Workspace cleanup left objects: {remaining}")
    finally:
        await connection.close()


def _is_write_sentinel_error(error: asyncpg.PostgresError) -> bool:
    return getattr(error, "sqlstate", None) == "55000" and (
        "legacy_workspace_write_forbidden" in str(error)
    )


async def assert_write_rejected(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        try:
            await connection.execute(
                "UPDATE workspaces SET name = name WHERE id = '__sentinel_probe__'"
            )
        except asyncpg.PostgresError as error:
            if not _is_write_sentinel_error(error):
                raise RuntimeError("legacy Workspace sentinel failed unexpectedly") from error
        else:
            raise RuntimeError("legacy Workspace sentinel accepted a write")
    finally:
        await connection.close()
