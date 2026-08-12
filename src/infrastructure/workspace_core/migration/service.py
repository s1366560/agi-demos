"""PostgreSQL execution engine for lossless Workspace migration."""

# pyright: reportImplicitStringConcatenation=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import asyncpg

from .contracts import SOURCE_COLUMN_CONTRACTS
from .model import (
    MIGRATION_VERSION,
    DatabaseRow,
    EntityMigrationReport,
    MigrationCommand,
    MigrationError,
    MigrationReport,
    MigrationScope,
    MigrationSpec,
    PreflightIssue,
    canonical_hash,
    canonical_json,
    decode_json,
)
from .preflight import PREFLIGHT_CHECKS
from .specs import MIGRATION_SPECS

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class WorkspaceMigrationService:
    """Run dry-run, execute, validate, and reverse-export against PostgreSQL."""

    def __init__(
        self,
        connection: asyncpg.Connection,
        *,
        specs: Sequence[MigrationSpec] = MIGRATION_SPECS,
    ) -> None:
        super().__init__()
        self._connection = connection
        self._specs = tuple(specs)
        self._validate_identifiers()

    async def run(
        self,
        command: MigrationCommand,
        *,
        migration_run_id: str,
        scope: MigrationScope = MigrationScope(),
        output_path: Path | None = None,
        force: bool = False,
    ) -> MigrationReport:
        """Execute one migration command and return a machine-readable report."""

        report = MigrationReport(
            command=command,
            migration_run_id=migration_run_id,
            migration_version=MIGRATION_VERSION,
            scope=scope,
        )
        report.preflight_issues.extend(await self._schema_issues())
        report.preflight_issues.extend(await self._data_issues())
        if report.preflight_issues:
            return report

        if command is MigrationCommand.REVERSE_EXPORT:
            if output_path is None:
                raise MigrationError("reverse-export requires an output path")
            report.exported_records = await self._reverse_export(output_path, scope, force=force)
            return report

        for spec in self._specs:
            rows = await self._source_rows(spec, scope)
            entity_report = self._source_report(spec, rows)
            report.entities.append(entity_report)
            if command is MigrationCommand.DRY_RUN:
                continue
            if command is MigrationCommand.EXECUTE:
                await self._execute_spec(spec, rows, migration_run_id, scope, entity_report)
            elif command is MigrationCommand.VALIDATE:
                await self._validate_spec(spec, rows, migration_run_id, scope, entity_report)
        return report

    def _validate_identifiers(self) -> None:
        for spec in self._specs:
            identifiers = (spec.target_table, *spec.target_columns, *spec.key_columns)
            if any(_IDENTIFIER.fullmatch(identifier) is None for identifier in identifiers):
                raise MigrationError(f"unsafe migration identifier in {spec.entity_type}")

    async def _schema_issues(self) -> list[PreflightIssue]:
        source_rows = await self._connection.fetch(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY($1::text[])
            """,
            list(SOURCE_COLUMN_CONTRACTS),
        )
        actual_source: dict[str, set[str]] = {}
        for row in source_rows:
            actual_source.setdefault(str(row["table_name"]), set()).add(str(row["column_name"]))

        issues: list[PreflightIssue] = []
        for table_name, expected in SOURCE_COLUMN_CONTRACTS.items():
            actual = actual_source.get(table_name, set())
            if actual != set(expected):
                missing = sorted(expected - actual)
                unexpected = sorted(actual - expected)
                issues.append(
                    PreflightIssue(
                        code="source_schema_drift",
                        description=f"legacy source schema drift for {table_name}",
                        count=len(missing) + len(unexpected),
                        samples=tuple(
                            [f"missing:{item}" for item in missing[:5]]
                            + [f"unexpected:{item}" for item in unexpected[:5]]
                        ),
                    )
                )

        target_rows = await self._connection.fetch(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'avernet'
            """
        )
        actual_target = {(str(row["table_name"]), str(row["column_name"])) for row in target_rows}
        expected_target = {
            (spec.target_table, column) for spec in self._specs for column in spec.target_columns
        }
        missing_target = sorted(expected_target - actual_target)
        if missing_target:
            issues.append(
                PreflightIssue(
                    code="target_schema_incomplete",
                    description="Avernet target schema is missing mapped columns",
                    count=len(missing_target),
                    samples=tuple(f"{table}.{column}" for table, column in missing_target[:10]),
                )
            )
        return issues

    async def _data_issues(self) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        for check in PREFLIGHT_CHECKS:
            count = cast(
                int,
                await self._connection.fetchval(f"SELECT count(*) FROM ({check.sql}) invalid"),
            )
            if not count:
                continue
            rows = await self._connection.fetch(
                f"SELECT sample FROM ({check.sql}) invalid LIMIT 10"
            )
            issues.append(
                PreflightIssue(
                    code=check.code,
                    description=check.description,
                    count=count,
                    samples=tuple(str(row["sample"]) for row in rows),
                )
            )
        return issues

    async def _source_rows(
        self,
        spec: MigrationSpec,
        scope: MigrationScope,
    ) -> list[DatabaseRow]:
        source_id = spec.source_id_column
        if _IDENTIFIER.fullmatch(source_id.lstrip("_")) is None:
            raise MigrationError(f"unsafe source id column in {spec.entity_type}")
        sql = f"""
            SELECT migration_source.*
            FROM ({spec.source_sql}) migration_source
            WHERE ($1::text IS NULL OR migration_source._tenant_id::text = $1)
              AND ($2::text IS NULL OR migration_source._project_id::text = $2)
              AND (
                    $3::text IS NULL
                    OR (
                        $4::boolean
                        AND EXISTS (
                            SELECT 1
                            FROM workspaces migration_scope_workspace
                            WHERE migration_scope_workspace.id::text = $3
                              AND migration_scope_workspace.tenant_id = migration_source._tenant_id
                              AND migration_scope_workspace.project_id = migration_source._project_id
                        )
                    )
                    OR (
                        NOT $4::boolean
                        AND migration_source._workspace_id::text = $3
                    )
              )
            ORDER BY migration_source._tenant_id, migration_source._project_id,
                     migration_source._workspace_id, migration_source.{source_id}
        """
        records = await self._connection.fetch(
            sql,
            scope.tenant_id,
            scope.project_id,
            scope.workspace_id,
            spec.project_scoped,
        )
        return [cast(DatabaseRow, dict(record)) for record in records]

    def _source_report(
        self,
        spec: MigrationSpec,
        rows: Sequence[DatabaseRow],
    ) -> EntityMigrationReport:
        source_ids = [str(row[spec.source_id_column]) for row in rows]
        mapped_values = [self._mapped_values(spec, row) for row in rows]
        target_ids = [spec.target_id(values) for values in mapped_values]
        if spec.reverse_mapper is not None and len(target_ids) != len(set(target_ids)):
            raise MigrationError(f"duplicate authoritative target key for {spec.entity_type}")
        content_hashes = [canonical_hash(values) for values in mapped_values]
        return EntityMigrationReport(
            entity_type=spec.entity_type,
            source_table=spec.source_table,
            target_table=spec.target_table,
            source_count=len(rows),
            primary_key_hash=canonical_hash(sorted(source_ids)),
            content_hash=canonical_hash(sorted(content_hashes)),
        )

    async def _execute_spec(
        self,
        spec: MigrationSpec,
        rows: Sequence[DatabaseRow],
        migration_run_id: str,
        scope: MigrationScope,
        report: EntityMigrationReport,
    ) -> None:
        current_row: DatabaseRow | None = None
        try:
            async with self._connection.transaction():
                for current_row in rows:
                    values = self._mapped_values(spec, current_row)
                    source_hash = canonical_hash(values)
                    await self._upsert_target(spec, values)
                    target = await self._fetch_target(spec, values)
                    target_hash = canonical_hash(target)
                    if source_hash != target_hash:
                        raise MigrationError(
                            f"target hash mismatch for {spec.entity_type}:"
                            f"{current_row[spec.source_id_column]}"
                        )
                    await self._record_ledger(
                        spec,
                        current_row,
                        values,
                        migration_run_id,
                        source_hash,
                        target_hash,
                        status="verified",
                    )
                    report.verified_count += 1
                await self._set_target_report(spec, rows, scope, report)
        except Exception as error:
            report.failed_count += 1
            if current_row is not None:
                await self._record_failure(spec, current_row, migration_run_id, error)
            raise MigrationError(f"migration failed for {spec.entity_type}") from error

    async def _validate_spec(
        self,
        spec: MigrationSpec,
        rows: Sequence[DatabaseRow],
        migration_run_id: str,
        scope: MigrationScope,
        report: EntityMigrationReport,
    ) -> None:
        current_row: DatabaseRow | None = None
        try:
            async with self._connection.transaction():
                for current_row in rows:
                    values = self._mapped_values(spec, current_row)
                    source_hash = canonical_hash(values)
                    target = await self._fetch_target(spec, values)
                    target_hash = canonical_hash(target)
                    if source_hash != target_hash:
                        raise MigrationError(
                            f"validation hash mismatch for {spec.entity_type}:"
                            f"{current_row[spec.source_id_column]}"
                        )
                    await self._record_ledger(
                        spec,
                        current_row,
                        values,
                        migration_run_id,
                        source_hash,
                        target_hash,
                        status="verified",
                    )
                    report.verified_count += 1
                await self._set_target_report(spec, rows, scope, report)
        except Exception as error:
            report.failed_count += 1
            if current_row is not None:
                await self._record_failure(spec, current_row, migration_run_id, error)
            raise MigrationError(f"validation failed for {spec.entity_type}") from error

    async def _set_target_report(
        self,
        spec: MigrationSpec,
        source_rows: Sequence[DatabaseRow],
        scope: MigrationScope,
        report: EntityMigrationReport,
    ) -> None:
        expected = [self._mapped_values(spec, row) for row in source_rows]
        expected_ids = sorted(spec.target_id(values) for values in expected)
        if spec.reverse_mapper is None:
            report.target_primary_key_hash = canonical_hash(expected_ids)
            report.target_content_hash = canonical_hash(
                sorted(canonical_hash(values) for values in expected)
            )
            return

        target_rows = await self._reverse_rows(spec, scope)
        target_ids = sorted(spec.target_id(row) for row in target_rows)
        if target_ids != expected_ids:
            raise MigrationError(f"target primary-key set mismatch for {spec.entity_type}")
        report.target_primary_key_hash = canonical_hash(target_ids)
        report.target_content_hash = canonical_hash(
            sorted(canonical_hash(row) for row in target_rows)
        )

    def _mapped_values(self, spec: MigrationSpec, row: DatabaseRow) -> dict[str, object]:
        values = spec.mapper(row)
        missing = set(spec.target_columns) - values.keys()
        unexpected = values.keys() - set(spec.target_columns)
        if missing or unexpected:
            raise MigrationError(
                f"mapping shape mismatch for {spec.entity_type}: "
                f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
            )
        return values

    async def _upsert_target(self, spec: MigrationSpec, values: Mapping[str, object]) -> None:
        placeholders = [
            f"${index}::jsonb" if column in spec.json_columns else f"${index}"
            for index, column in enumerate(spec.target_columns, start=1)
        ]
        conflict_sql = ", ".join(spec.key_columns)
        mutable_columns = [
            column for column in spec.target_columns if column not in spec.key_columns
        ]
        if mutable_columns:
            assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in mutable_columns)
            changed = " OR ".join(
                f"{spec.target_table}.{column} IS DISTINCT FROM EXCLUDED.{column}"
                for column in mutable_columns
            )
            conflict_action = f"DO UPDATE SET {assignments} WHERE {changed}"
        else:
            conflict_action = "DO NOTHING"
        sql = (
            f"INSERT INTO avernet.{spec.target_table} ({', '.join(spec.target_columns)}) "
            f"VALUES ({', '.join(placeholders)}) ON CONFLICT ({conflict_sql}) "
            f"{conflict_action}"
        )
        parameters = [
            canonical_json(values[column]) if column in spec.json_columns else values[column]
            for column in spec.target_columns
        ]
        _ = await self._connection.execute(sql, *parameters)

    async def _fetch_target(
        self,
        spec: MigrationSpec,
        values: Mapping[str, object],
    ) -> dict[str, object]:
        predicates = [f"{column} = ${index}" for index, column in enumerate(spec.key_columns, 1)]
        sql = (
            f"SELECT {', '.join(spec.target_columns)} FROM avernet.{spec.target_table} "
            f"WHERE {' AND '.join(predicates)}"
        )
        record = await self._connection.fetchrow(
            sql,
            *(values[column] for column in spec.key_columns),
        )
        if record is None:
            raise MigrationError(f"missing target row for {spec.entity_type}")
        result = dict(record)
        for column in spec.json_columns:
            result[column] = decode_json(result.get(column), default=None)
        return cast(dict[str, object], result)

    async def _record_ledger(
        self,
        spec: MigrationSpec,
        source_row: DatabaseRow,
        values: Mapping[str, object],
        migration_run_id: str,
        source_hash: str,
        target_hash: str | None,
        *,
        status: str,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        _ = await self._connection.execute(
            """
            INSERT INTO avernet.workspace_migration_ledger (
                migration_run_id, migration_version, tenant_id, project_id, workspace_id,
                entity_type, source_id, target_table, target_id, source_hash, target_hash,
                status, attempt_count, error_code, error_detail, migrated_at, verified_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::varchar, 1, $13, $14,
                CASE WHEN $12::text IN ('migrated', 'verified') THEN CURRENT_TIMESTAMP END,
                CASE WHEN $12::text = 'verified' THEN CURRENT_TIMESTAMP END
            )
            ON CONFLICT (migration_run_id, entity_type, source_id) DO UPDATE SET
                migration_version = EXCLUDED.migration_version,
                tenant_id = EXCLUDED.tenant_id,
                project_id = EXCLUDED.project_id,
                workspace_id = EXCLUDED.workspace_id,
                target_table = EXCLUDED.target_table,
                target_id = EXCLUDED.target_id,
                source_hash = EXCLUDED.source_hash,
                target_hash = EXCLUDED.target_hash,
                status = EXCLUDED.status,
                attempt_count = avernet.workspace_migration_ledger.attempt_count + 1,
                error_code = EXCLUDED.error_code,
                error_detail = EXCLUDED.error_detail,
                migrated_at = EXCLUDED.migrated_at,
                verified_at = EXCLUDED.verified_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            migration_run_id,
            MIGRATION_VERSION,
            str(source_row["_tenant_id"]),
            str(source_row["_project_id"]),
            str(source_row["_workspace_id"])
            if source_row.get("_workspace_id") is not None
            else None,
            spec.entity_type,
            str(source_row[spec.source_id_column]),
            spec.target_table,
            spec.target_id(values),
            source_hash,
            target_hash,
            status,
            error_code,
            error_detail,
        )

    async def _record_failure(
        self,
        spec: MigrationSpec,
        source_row: DatabaseRow,
        migration_run_id: str,
        error: Exception,
    ) -> None:
        values = spec.mapper(source_row)
        async with self._connection.transaction():
            await self._record_ledger(
                spec,
                source_row,
                values,
                migration_run_id,
                canonical_hash(values),
                None,
                status="failed",
                error_code=type(error).__name__[:80],
                error_detail=str(error)[:2000],
            )

    async def _reverse_export(
        self,
        output_path: Path,
        scope: MigrationScope,
        *,
        force: bool,
    ) -> int:
        if output_path.exists() and not force:
            raise MigrationError(f"reverse-export output already exists: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.tmp")
        count = 0
        try:
            with temporary_path.open("w", encoding="utf-8") as output:
                for spec in self._specs:
                    if spec.reverse_mapper is None:
                        continue
                    rows = await self._reverse_rows(spec, scope)
                    for row in rows:
                        source = spec.reverse_mapper(row)
                        source_table = str(source.pop("_source_table", spec.source_table))
                        _ = output.write(
                            canonical_json(
                                {
                                    "migration_version": MIGRATION_VERSION,
                                    "source_table": source_table,
                                    "source_row": source,
                                }
                            )
                        )
                        _ = output.write("\n")
                        count += 1
            os.replace(temporary_path, output_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return count

    async def _reverse_rows(
        self,
        spec: MigrationSpec,
        scope: MigrationScope,
    ) -> list[DatabaseRow]:
        target_alias = "target"
        has_tenant = "tenant_id" in spec.target_columns
        has_project = "project_id" in spec.target_columns
        has_workspace = "workspace_id" in spec.target_columns
        if not has_workspace:
            raise MigrationError(f"reverse mapping lacks workspace scope: {spec.entity_type}")
        join = ""
        tenant_expression = f"{target_alias}.tenant_id" if has_tenant else "profile.tenant_id"
        project_expression = f"{target_alias}.project_id" if has_project else "profile.project_id"
        if not has_tenant or not has_project:
            join = (
                " JOIN avernet.workspace_profiles profile"
                f" ON profile.workspace_id = {target_alias}.workspace_id"
            )
        sql = f"""
            SELECT {", ".join(f"{target_alias}.{column}" for column in spec.target_columns)}
            FROM avernet.{spec.target_table} {target_alias}{join}
            WHERE ($1::text IS NULL OR {tenant_expression}::text = $1)
              AND ($2::text IS NULL OR {project_expression}::text = $2)
              AND ($3::text IS NULL OR {target_alias}.workspace_id::text = $3)
            ORDER BY {target_alias}.workspace_id, {", ".join(f"{target_alias}.{column}" for column in spec.key_columns)}
        """
        records = await self._connection.fetch(
            sql,
            scope.tenant_id,
            scope.project_id,
            scope.workspace_id,
        )
        rows: list[DatabaseRow] = []
        for record in records:
            values = dict(record)
            for column in spec.json_columns:
                values[column] = decode_json(values.get(column), default=None)
            rows.append(cast(DatabaseRow, values))
        return rows
