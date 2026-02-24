"""SubAgent run repository abstractions with DB + Redis-backed implementations."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus

logger = logging.getLogger(__name__)


class SubAgentRunRepository(Protocol):
    """Repository contract for SubAgent run persistence."""

    def load_runs(self) -> dict[str, dict[str, SubAgentRun]]:
        """Load all runs indexed by conversation_id -> run_id."""

    def save_runs(self, runs: Mapping[str, Mapping[str, SubAgentRun]]) -> None:
        """Persist full run snapshot."""

    def close(self) -> None:
        """Release repository resources."""


class SqliteSubAgentRunRepository:
    """SQLite-backed repository for SubAgent run snapshots."""

    def __init__(
        self,
        sqlite_path: str,
        table_name: str = "subagent_run_snapshots",
    ) -> None:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
            raise ValueError(f"Invalid table_name: {table_name}")
        self._db_path = Path(sqlite_path).expanduser().resolve()
        self._table_name = table_name
        self._initialize_schema()

    def load_runs(self) -> dict[str, dict[str, SubAgentRun]]:
        if not self._db_path.exists():
            return {}
        try:
            with closing(sqlite3.connect(self._db_path)) as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    f"SELECT payload FROM {self._table_name} WHERE id = 1"
                ).fetchone()
        except Exception as exc:
            logger.warning(f"[SqliteSubAgentRunRepository] Failed to load runs: {exc}")
            return {}
        if not row:
            return {}
        return _deserialize_snapshot(row[0])

    def save_runs(self, runs: Mapping[str, Mapping[str, SubAgentRun]]) -> None:
        payload = _serialize_snapshot(runs)
        updated_at = datetime.now(UTC).isoformat()
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path)) as conn:
                self._ensure_schema(conn)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    f"""
                    INSERT INTO {self._table_name} (id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (payload, updated_at),
                )
                conn.commit()
        except Exception as exc:
            logger.warning(f"[SqliteSubAgentRunRepository] Failed to persist runs: {exc}")

    def _initialize_schema(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path)) as conn:
                self._ensure_schema(conn)
                conn.commit()
        except Exception as exc:
            logger.warning(f"[SqliteSubAgentRunRepository] Failed to initialize schema: {exc}")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def close(self) -> None:
        """No-op for sqlite repository (connections are per-operation)."""
        return


class PostgresSubAgentRunRepository:
    """PostgreSQL-backed repository for SubAgent run snapshots."""

    def __init__(
        self,
        postgres_dsn: str,
        table_name: str = "subagent_run_snapshots",
        connect_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
            raise ValueError(f"Invalid table_name: {table_name}")
        dsn = postgres_dsn.strip()
        if not dsn:
            raise ValueError("postgres_dsn must not be empty")
        self._postgres_dsn = dsn
        self._table_name = table_name
        self._connect_factory = connect_factory
        self._initialize_schema()

    def load_runs(self) -> dict[str, dict[str, SubAgentRun]]:
        conn: Any = None
        try:
            conn = self._connect()
            with closing(conn):
                with conn.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"SELECT payload FROM {self._table_name} WHERE id = 1"
                    )
                    row = cursor.fetchone()
                conn.commit()
        except Exception as exc:
            logger.warning(f"[PostgresSubAgentRunRepository] Failed to load runs: {exc}")
            self._safe_rollback(conn)
            return {}
        if not row:
            return {}
        payload = row[0]
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False)
        return _deserialize_snapshot(str(payload))

    def save_runs(self, runs: Mapping[str, Mapping[str, SubAgentRun]]) -> None:
        payload = _serialize_snapshot(runs)
        updated_at = datetime.now(UTC).isoformat()
        conn: Any = None
        try:
            conn = self._connect()
            with closing(conn):
                with conn.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"""
                        INSERT INTO {self._table_name} (id, payload, updated_at)
                        VALUES (1, %s, %s)
                        ON CONFLICT(id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (payload, updated_at),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning(f"[PostgresSubAgentRunRepository] Failed to persist runs: {exc}")
            self._safe_rollback(conn)

    def _initialize_schema(self) -> None:
        conn: Any = None
        try:
            conn = self._connect()
            with closing(conn):
                with conn.cursor() as cursor:
                    self._ensure_schema(cursor)
                conn.commit()
        except Exception as exc:
            logger.warning(f"[PostgresSubAgentRunRepository] Failed to initialize schema: {exc}")
            self._safe_rollback(conn)

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory(self._postgres_dsn)
        try:
            import psycopg2
        except Exception as exc:
            raise RuntimeError(
                "psycopg2 is required for PostgresSubAgentRunRepository"
            ) from exc
        return psycopg2.connect(self._postgres_dsn)

    def _ensure_schema(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    @staticmethod
    def _safe_rollback(conn: Any) -> None:
        if conn is None:
            return
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            with suppress(Exception):
                rollback()

    def close(self) -> None:
        """No-op for postgres repository (connections are per-operation)."""
        return


class RedisRunSnapshotCache:
    """Redis cache wrapper for SubAgent run snapshots."""

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        key: str = "subagent:runs:snapshot:v1",
        ttl_seconds: int = 60,
        client: Any | None = None,
    ) -> None:
        self._key = key
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._client = client
        if self._client is None and redis_url:
            try:
                import redis

                self._client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=5.0,
                    socket_connect_timeout=5.0,
                )
            except Exception as exc:
                logger.warning(f"[RedisRunSnapshotCache] Failed to initialize client: {exc}")
                self._client = None

    def load_runs(self) -> dict[str, dict[str, SubAgentRun]] | None:
        if self._client is None:
            return None
        try:
            cached = self._client.get(self._key)
        except Exception as exc:
            logger.warning(f"[RedisRunSnapshotCache] Failed to read cache: {exc}")
            return None
        if cached is None:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        return _deserialize_snapshot(cached)

    def save_runs(self, runs: Mapping[str, Mapping[str, SubAgentRun]]) -> None:
        if self._client is None:
            return
        try:
            self._client.setex(self._key, self._ttl_seconds, _serialize_snapshot(runs))
        except Exception as exc:
            logger.warning(f"[RedisRunSnapshotCache] Failed to update cache: {exc}")

    def close(self) -> None:
        """Close redis client when available."""
        if self._client is None:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            with suppress(Exception):
                close()


class HybridSubAgentRunRepository:
    """Repository using SQLite as source of truth and Redis as acceleration cache."""

    def __init__(
        self,
        db_repository: SubAgentRunRepository,
        redis_cache: RedisRunSnapshotCache | None = None,
    ) -> None:
        self._db_repository = db_repository
        self._redis_cache = redis_cache

    def load_runs(self) -> dict[str, dict[str, SubAgentRun]]:
        if self._redis_cache is not None:
            cached = self._redis_cache.load_runs()
            if cached is not None:
                return cached

        runs = self._db_repository.load_runs()
        if self._redis_cache is not None:
            self._redis_cache.save_runs(runs)
        return runs

    def save_runs(self, runs: Mapping[str, Mapping[str, SubAgentRun]]) -> None:
        self._db_repository.save_runs(runs)
        if self._redis_cache is not None:
            self._redis_cache.save_runs(runs)

    def close(self) -> None:
        """Close repository and cache resources."""
        close_db = getattr(self._db_repository, "close", None)
        if callable(close_db):
            close_db()
        if self._redis_cache is not None:
            self._redis_cache.close()


def _serialize_snapshot(runs: Mapping[str, Mapping[str, SubAgentRun]]) -> str:
    payload = {
        "version": 1,
        "conversations": {
            conversation_id: {
                run_id: run.to_event_data()
                for run_id, run in bucket.items()
            }
            for conversation_id, bucket in runs.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_snapshot(payload: str) -> dict[str, dict[str, SubAgentRun]]:
    try:
        raw = json.loads(payload)
    except Exception:
        return {}

    if not isinstance(raw, dict) or raw.get("version") != 1:
        return {}
    conversations = raw.get("conversations", {})
    if not isinstance(conversations, dict):
        return {}

    loaded: dict[str, dict[str, SubAgentRun]] = {}
    for conversation_id, run_payloads in conversations.items():
        if not isinstance(run_payloads, dict):
            continue
        bucket: dict[str, SubAgentRun] = {}
        for run_id, run_payload in run_payloads.items():
            run = _deserialize_run(run_payload)
            if run is not None:
                bucket[run_id] = run
        if bucket:
            loaded[conversation_id] = bucket
    return loaded


def _deserialize_run(payload: Any) -> SubAgentRun | None:
    if not isinstance(payload, dict):
        return None
    try:
        status = SubAgentRunStatus(str(payload.get("status", SubAgentRunStatus.PENDING.value)))
    except ValueError:
        status = SubAgentRunStatus.PENDING

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    try:
        return SubAgentRun(
            run_id=str(payload.get("run_id") or ""),
            conversation_id=str(payload.get("conversation_id") or ""),
            subagent_name=str(payload.get("subagent_name") or ""),
            task=str(payload.get("task") or ""),
            status=status,
            created_at=_parse_datetime(payload.get("created_at")) or datetime.now(UTC),
            started_at=_parse_datetime(payload.get("started_at")),
            ended_at=_parse_datetime(payload.get("ended_at")),
            summary=_optional_str(payload.get("summary")),
            error=_optional_str(payload.get("error")),
            execution_time_ms=_optional_int(payload.get("execution_time_ms")),
            tokens_used=_optional_int(payload.get("tokens_used")),
            metadata=metadata,
        )
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
