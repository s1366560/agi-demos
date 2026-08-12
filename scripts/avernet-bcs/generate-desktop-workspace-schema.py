#!/usr/bin/env python3
"""Generate the Desktop SQLite Workspace extension schema from PostgreSQL metadata."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

SCHEMA_VERSION = 1
TABLES = (
    "project_principal_memberships",
    "workspace_profiles",
    "workspace_members",
    "workspace_principal_identities",
    "workspace_agent_policies",
    "workspace_agent_bindings",
    "workspace_tasks",
    "workspace_task_attempts",
    "workspace_task_receipts",
    "workspace_blackboard_posts",
    "workspace_blackboard_replies",
    "workspace_files",
    "workspace_topology_nodes",
    "workspace_topology_edges",
    "workspace_objectives",
    "workspace_genes",
    "workspace_authorities",
    "workspace_revision_credentials",
    "workspace_mutation_receipts",
    "workspace_plans",
    "workspace_plan_nodes",
    "workspace_plan_blackboard_entries",
    "workspace_plan_events",
    "workspace_outbox",
    "workspace_pipeline_contracts",
    "workspace_pipeline_runs",
    "workspace_pipeline_stage_runs",
    "workspace_deployments",
    "workspace_agent_runtime_correlations",
    "workspace_execution_terminals",
    "workspace_migration_ledger",
    "workspace_judge_audits",
    "workspace_message_correlations",
    "workspace_message_delivery_outbox",
    "workspace_task_dispatch_outbox",
    "workspace_contexts",
    "workspace_context_events",
    "workspace_context_outbox",
    "workspace_file_operations",
    "workspace_file_compensations",
    "workspace_objective_task_projections",
    "workspace_autonomy_ticks",
)


def query(container: str, database: str, sql: str) -> list[list[str]]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            database,
            "-AtF",
            "\t",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.split("\t") for line in completed.stdout.splitlines() if line]


def sqlite_type(data_type: str) -> str:
    return {
        "bigint": "INTEGER",
        "boolean": "INTEGER",
        "character": "TEXT",
        "character varying": "TEXT",
        "double precision": "REAL",
        "integer": "INTEGER",
        "jsonb": "TEXT",
        "text": "TEXT",
        "timestamp with time zone": "TEXT",
    }[data_type]


def sqlite_default(value: str) -> str | None:
    if not value or value.startswith("nextval("):
        return None
    value = value.replace("::jsonb", "").replace("::character varying", "")
    return {"true": "1", "false": "0"}.get(value, value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="memstack-postgres")
    parser.add_argument("--database", default="memstack")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    columns = query(
        args.container,
        args.database,
        """SELECT table_name,column_name,data_type,is_nullable,column_default,is_identity
           FROM information_schema.columns
           WHERE table_schema='avernet'
             AND (table_name LIKE 'workspace_%' OR table_name='project_principal_memberships')
           ORDER BY table_name,ordinal_position""",
    )
    keys = query(
        args.container,
        args.database,
        """SELECT tc.table_name,tc.constraint_type,tc.constraint_name,
                  string_agg(kcu.column_name,',' ORDER BY kcu.ordinal_position)
           FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage kcu
             ON kcu.constraint_schema=tc.constraint_schema
            AND kcu.constraint_name=tc.constraint_name
           WHERE tc.table_schema='avernet'
             AND (tc.table_name LIKE 'workspace_%'
                  OR tc.table_name='project_principal_memberships')
             AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE')
           GROUP BY 1,2,3 ORDER BY 1,2,3""",
    )
    columns_by_table: dict[str, list[list[str]]] = defaultdict(list)
    keys_by_table: dict[str, list[list[str]]] = defaultdict(list)
    for row in columns:
        columns_by_table[row[0]].append(row)
    for row in keys:
        keys_by_table[row[0]].append(row)

    expected_tables: set[str] = set(TABLES)
    missing = sorted(expected_tables - set(columns_by_table))
    if missing:
        raise SystemExit(f"authoritative schema is missing: {', '.join(missing)}")

    statements = [
        """CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""
    ]
    for table in TABLES:
        table_keys = keys_by_table[table]
        primary = next(row[3] for row in table_keys if row[1] == "PRIMARY KEY")
        definitions: list[str] = []
        inline_primary = False
        for _, column, data_type, nullable, default, identity in columns_by_table[table]:
            if identity == "YES" and primary == column:
                definitions.append(f"{column} INTEGER PRIMARY KEY AUTOINCREMENT")
                inline_primary = True
                continue
            definition = f"{column} {sqlite_type(data_type)}"
            if nullable == "NO":
                definition += " NOT NULL"
            normalized_default = sqlite_default(default)
            if normalized_default is not None:
                definition += f" DEFAULT {normalized_default}"
            definitions.append(definition)
        if not inline_primary:
            definitions.append(f"PRIMARY KEY ({primary})")
        seen: set[str] = set()
        for _, kind, _, key_columns in table_keys:
            if kind == "UNIQUE" and key_columns not in seen:
                seen.add(key_columns)
                definitions.append(f"UNIQUE ({key_columns})")
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {table} (\n    "
            + ",\n    ".join(definitions)
            + "\n)"
        )

    schema = ";\n\n".join(statements) + ";\n"
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(schema)
        actual = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    if not set(TABLES).issubset(actual):
        raise SystemExit("generated SQLite schema failed completeness validation")
    args.output.write_text(schema, encoding="utf-8")
    print(f"generated Desktop Workspace SQLite schema v{SCHEMA_VERSION}: {args.output}")


if __name__ == "__main__":
    main()
