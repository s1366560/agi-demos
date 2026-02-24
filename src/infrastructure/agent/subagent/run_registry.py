"""Registry for SubAgent run lifecycle tracking with optional persistence."""

import json
import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.agent.subagent.run_repository import (
    HybridSubAgentRunRepository,
    PostgresSubAgentRunRepository,
    RedisRunSnapshotCache,
    SqliteSubAgentRunRepository,
    SubAgentRunRepository,
)

logger = logging.getLogger(__name__)


class SubAgentRunRegistry:
    """Tracks delegated SubAgent runs grouped by conversation."""

    _ACTIVE_STATUSES: ClassVar[set] = {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}
    _PERSIST_VERSION = 1

    def __init__(
        self,
        max_runs_per_conversation: int = 200,
        persistence_path: str | None = None,
        postgres_persistence_dsn: str | None = None,
        sqlite_persistence_path: str | None = None,
        redis_cache_url: str | None = None,
        redis_cache_ttl_seconds: int = 60,
        repository: SubAgentRunRepository | None = None,
        terminal_retention_seconds: int = 86400,
        recover_inflight_on_boot: bool = True,
        sync_across_processes: bool = True,
    ) -> None:
        self._runs_by_conversation: dict[str, dict[str, SubAgentRun]] = {}
        self._max_runs_per_conversation = max(1, max_runs_per_conversation)
        self._persistence_path = Path(persistence_path).expanduser() if persistence_path else None
        self._repository: SubAgentRunRepository | None = repository
        if self._repository is None:
            db_repo: SubAgentRunRepository | None = None
            if postgres_persistence_dsn:
                db_repo = PostgresSubAgentRunRepository(postgres_persistence_dsn)
            elif sqlite_persistence_path:
                db_repo = SqliteSubAgentRunRepository(sqlite_persistence_path)
            if db_repo is not None and redis_cache_url:
                redis_cache = RedisRunSnapshotCache(
                    redis_url=redis_cache_url,
                    ttl_seconds=redis_cache_ttl_seconds,
                )
                self._repository = HybridSubAgentRunRepository(db_repo, redis_cache)
            elif db_repo is not None:
                self._repository = db_repo
        self._lock_path = (
            self._persistence_path.with_suffix(f"{self._persistence_path.suffix}.lock")
            if self._persistence_path
            else None
        )
        self._terminal_retention_seconds = max(0, terminal_retention_seconds)
        self._recover_inflight_on_boot = recover_inflight_on_boot
        self._sync_across_processes = bool(
            sync_across_processes and (self._persistence_path or self._repository is not None)
        )
        self._load_from_disk()

    def create_run(
        self,
        conversation_id: str,
        subagent_name: str,
        task: str,
        metadata: dict[str, object] | None = None,
        run_id: str | None = None,
        requester_session_key: str | None = None,
        parent_run_id: str | None = None,
        lineage_root_run_id: str | None = None,
    ) -> SubAgentRun:
        """Create and register a new pending run."""
        run_metadata = dict(metadata or {})
        if requester_session_key:
            run_metadata.setdefault("requester_session_key", requester_session_key)
        if parent_run_id:
            run_metadata.setdefault("parent_run_id", parent_run_id)
        if lineage_root_run_id:
            run_metadata.setdefault("lineage_root_run_id", lineage_root_run_id)

        with self._with_registry_lock(exclusive=True):
            self._sync_from_disk_locked()
            run = SubAgentRun(
                run_id=run_id or uuid.uuid4().hex,
                conversation_id=conversation_id,
                subagent_name=subagent_name,
                task=task,
                metadata=run_metadata,
            )
            if not run.metadata.get("lineage_root_run_id"):
                run = replace(run, metadata={**run.metadata, "lineage_root_run_id": run.run_id})
            return self._upsert_locked(run)

    def mark_running(
        self,
        conversation_id: str,
        run_id: str,
        metadata: dict[str, object] | None = None,
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Transition run to RUNNING."""
        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=lambda run: (
                replace(run.start(), metadata={**run.metadata, **(metadata or {})})
                if metadata
                else run.start()
            ),
        )

    def mark_completed(
        self,
        conversation_id: str,
        run_id: str,
        summary: str | None = None,
        tokens_used: int | None = None,
        execution_time_ms: int | None = None,
        metadata: dict[str, object] | None = None,
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Transition run to COMPLETED."""

        def _mutator(run: SubAgentRun) -> SubAgentRun:
            completed = run.complete(
                summary=summary,
                tokens_used=tokens_used,
                execution_time_ms=execution_time_ms,
            )
            if metadata:
                completed = replace(completed, metadata={**completed.metadata, **metadata})
            return completed

        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=_mutator,
        )

    def mark_failed(
        self,
        conversation_id: str,
        run_id: str,
        error: str,
        execution_time_ms: int | None = None,
        metadata: dict[str, object] | None = None,
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Transition run to FAILED."""

        def _mutator(run: SubAgentRun) -> SubAgentRun:
            failed = run.fail(error=error, execution_time_ms=execution_time_ms)
            if metadata:
                failed = replace(failed, metadata={**failed.metadata, **metadata})
            return failed

        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=_mutator,
        )

    def mark_cancelled(
        self,
        conversation_id: str,
        run_id: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Transition run to CANCELLED."""

        def _mutator(run: SubAgentRun) -> SubAgentRun:
            cancelled = run.cancel(reason=reason)
            if metadata:
                cancelled = replace(cancelled, metadata={**cancelled.metadata, **metadata})
            return cancelled

        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=_mutator,
        )

    def mark_timed_out(
        self,
        conversation_id: str,
        run_id: str,
        reason: str = "SubAgent execution timed out",
        metadata: dict[str, object] | None = None,
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Transition run to TIMED_OUT."""

        def _mutator(run: SubAgentRun) -> SubAgentRun:
            timed_out = run.time_out(reason=reason)
            if metadata:
                timed_out = replace(timed_out, metadata={**timed_out.metadata, **metadata})
            return timed_out

        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=_mutator,
        )

    def attach_metadata(
        self,
        conversation_id: str,
        run_id: str,
        metadata: dict[str, object],
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        """Merge metadata into a run."""

        def _mutator(run: SubAgentRun) -> SubAgentRun:
            merged = dict(run.metadata)
            merged.update(metadata)
            return replace(run, metadata=merged)

        return self._mutate_run(
            conversation_id=conversation_id,
            run_id=run_id,
            expected_statuses=expected_statuses,
            mutator=_mutator,
        )

    def get_run(self, conversation_id: str, run_id: str) -> SubAgentRun | None:
        """Get one run by conversation + run id."""
        self._sync_from_disk()
        return self._runs_by_conversation.get(conversation_id, {}).get(run_id)

    def list_runs(
        self,
        conversation_id: str,
        statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> list[SubAgentRun]:
        """List runs for a conversation in reverse chronological order."""
        self._sync_from_disk()
        runs = list(self._runs_by_conversation.get(conversation_id, {}).values())
        if statuses:
            allowed = set(statuses)
            runs = [run for run in runs if run.status in allowed]
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return runs

    def list_runs_for_requester(
        self,
        conversation_id: str,
        requester_session_key: str,
        *,
        visibility: str = "self",
        statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> list[SubAgentRun]:
        """List runs scoped by requester visibility boundary."""
        runs = self.list_runs(conversation_id, statuses=statuses)
        key = requester_session_key.strip()
        if not key or visibility == "all":
            return runs
        if visibility not in {"self", "tree"}:
            return []
        if visibility == "self":
            return [run for run in runs if self._run_requester_key(run) == key]

        # tree: requester-owned roots and all descendants.
        bucket = self._runs_by_conversation.get(conversation_id, {})
        children_by_parent: dict[str, list[str]] = {}
        for run in bucket.values():
            parent_id = str(run.metadata.get("parent_run_id") or "").strip()
            if parent_id:
                children_by_parent.setdefault(parent_id, []).append(run.run_id)

        visible_ids: set[str] = set()
        queue: list[str] = []
        for run in bucket.values():
            if self._run_requester_key(run) == key:
                visible_ids.add(run.run_id)
                queue.append(run.run_id)

        while queue:
            parent_run_id = queue.pop(0)
            for child_run_id in children_by_parent.get(parent_run_id, []):
                if child_run_id in visible_ids:
                    continue
                visible_ids.add(child_run_id)
                queue.append(child_run_id)

        return [run for run in runs if run.run_id in visible_ids]

    def list_descendant_runs(
        self,
        conversation_id: str,
        parent_run_id: str,
        *,
        include_terminal: bool = True,
    ) -> list[SubAgentRun]:
        """List descendants of a run using metadata.parent_run_id."""
        self._sync_from_disk()
        bucket = self._runs_by_conversation.get(conversation_id, {})
        children_by_parent: dict[str, list[SubAgentRun]] = {}
        for run in bucket.values():
            parent_id = str(run.metadata.get("parent_run_id") or "").strip()
            if not parent_id:
                continue
            children_by_parent.setdefault(parent_id, []).append(run)

        queue = [parent_run_id]
        visited: set[str] = set()
        descendants: list[SubAgentRun] = []
        while queue:
            current = queue.pop(0)
            for child in children_by_parent.get(current, []):
                if child.run_id in visited:
                    continue
                visited.add(child.run_id)
                queue.append(child.run_id)
                if include_terminal or child.status in self._ACTIVE_STATUSES:
                    descendants.append(child)

        descendants.sort(key=lambda run: run.created_at)
        return descendants

    def count_active_runs(self, conversation_id: str) -> int:
        """Count active (pending/running) runs for a conversation."""
        self._sync_from_disk()
        return len(
            [
                run
                for run in self._runs_by_conversation.get(conversation_id, {}).values()
                if run.status in self._ACTIVE_STATUSES
            ]
        )

    def count_active_runs_for_lineage(
        self,
        conversation_id: str,
        lineage_root_run_id: str,
    ) -> int:
        """Count active runs for one lineage root."""
        self._sync_from_disk()
        root_id = lineage_root_run_id.strip()
        if not root_id:
            return 0
        count = 0
        for run in self._runs_by_conversation.get(conversation_id, {}).values():
            if run.status not in self._ACTIVE_STATUSES:
                continue
            lineage_id = str(run.metadata.get("lineage_root_run_id") or run.run_id).strip()
            if lineage_id == root_id:
                count += 1
        return count

    @property
    def terminal_retention_seconds(self) -> int:
        """Configured retention window for terminal runs."""
        return self._terminal_retention_seconds

    def count_active_runs_for_requester(
        self,
        conversation_id: str,
        requester_session_key: str,
    ) -> int:
        """Count active runs scoped to a requester session key."""
        self._sync_from_disk()
        key = requester_session_key.strip()
        if not key:
            return self.count_active_runs(conversation_id)
        return len(
            [
                run
                for run in self._runs_by_conversation.get(conversation_id, {}).values()
                if run.status in self._ACTIVE_STATUSES
                and str(run.metadata.get("requester_session_key") or "").strip() == key
            ]
        )

    @staticmethod
    def _run_requester_key(run: SubAgentRun) -> str:
        return str(run.metadata.get("requester_session_key") or "").strip()

    def _mutate_run(
        self,
        conversation_id: str,
        run_id: str,
        *,
        mutator: Callable[[SubAgentRun], SubAgentRun],
        expected_statuses: Sequence[SubAgentRunStatus] | None = None,
    ) -> SubAgentRun | None:
        with self._with_registry_lock(exclusive=True):
            self._sync_from_disk_locked()
            run = self._runs_by_conversation.get(conversation_id, {}).get(run_id)
            if run is None:
                return None
            if expected_statuses and run.status not in set(expected_statuses):
                return None
            try:
                updated = mutator(run)
            except ValueError:
                return None
            return self._upsert_locked(updated)

    def _upsert(self, run: SubAgentRun) -> SubAgentRun:
        with self._with_registry_lock(exclusive=True):
            self._sync_from_disk_locked()
            return self._upsert_locked(run)

    def _upsert_locked(self, run: SubAgentRun) -> SubAgentRun:
        bucket = self._runs_by_conversation.setdefault(run.conversation_id, {})
        bucket[run.run_id] = run
        self._evict_if_needed(run.conversation_id)
        self._persist_locked()
        return run

    def _evict_if_needed(self, conversation_id: str) -> None:
        bucket = self._runs_by_conversation.get(conversation_id, {})
        if not bucket:
            return

        self._evict_expired_terminal_runs(conversation_id)
        if len(bucket) <= self._max_runs_per_conversation:
            return

        terminal_runs = [run for run in bucket.values() if run.status not in self._ACTIVE_STATUSES]
        terminal_runs.sort(key=lambda item: item.ended_at or item.created_at)

        while len(bucket) > self._max_runs_per_conversation and terminal_runs:
            to_remove = terminal_runs.pop(0)
            bucket.pop(to_remove.run_id, None)

    def _evict_expired_terminal_runs(self, conversation_id: str) -> None:
        if self._terminal_retention_seconds <= 0:
            return
        bucket = self._runs_by_conversation.get(conversation_id, {})
        if not bucket:
            return
        threshold = datetime.now(UTC) - timedelta(seconds=self._terminal_retention_seconds)
        for run in list(bucket.values()):
            if run.status in self._ACTIVE_STATUSES:
                continue
            ended_at = run.ended_at or run.created_at
            if ended_at <= threshold:
                bucket.pop(run.run_id, None)

    @contextmanager
    def _with_registry_lock(self, *, exclusive: bool) -> Iterator[None]:
        if not self._sync_across_processes or not self._lock_path or fcntl is None:
            yield
            return
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_file.fileno(), lock_mode)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _sync_from_disk(self) -> None:
        if not self._sync_across_processes:
            return
        with self._with_registry_lock(exclusive=False):
            self._sync_from_disk_locked()

    def _sync_from_disk_locked(self) -> None:
        self._load_from_disk_unlocked(recover_inflight=False)

    def _load_from_disk(self) -> None:
        if not self._persistence_path and self._repository is None:
            return
        if self._sync_across_processes:
            with self._with_registry_lock(exclusive=False):
                self._load_from_disk_unlocked(recover_inflight=self._recover_inflight_on_boot)
            return
        self._load_from_disk_unlocked(recover_inflight=self._recover_inflight_on_boot)

    def _load_from_disk_unlocked(self, *, recover_inflight: bool) -> None:
        if self._repository is not None:
            self._load_from_repository()
        else:
            self._load_from_json_file()
        if recover_inflight:
            self._recover_inflight_runs()

    def _load_from_repository(self) -> None:
        """Load runs from the repository adapter."""
        try:
            self._runs_by_conversation = self._repository.load_runs()
        except Exception as exc:
            logger.warning(f"[SubAgentRunRegistry] Failed to load repository runs: {exc}")
            self._runs_by_conversation = {}

    def _load_from_json_file(self) -> None:
        """Load runs from the JSON persistence file."""
        if not self._persistence_path or not self._persistence_path.exists():
            return
        try:
            raw = json.loads(self._persistence_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[SubAgentRunRegistry] Failed to load persisted runs: {exc}")
            return

        if not isinstance(raw, dict) or raw.get("version") != self._PERSIST_VERSION:
            logger.warning("[SubAgentRunRegistry] Ignoring unknown persisted registry format")
            return
        conversations = raw.get("conversations", {})
        if not isinstance(conversations, dict):
            return

        self._runs_by_conversation = self._deserialize_conversations(conversations)

    def _deserialize_conversations(
        self, conversations: dict[str, Any]
    ) -> dict[str, dict[str, SubAgentRun]]:
        """Deserialize conversation run buckets from raw dict."""
        loaded: dict[str, dict[str, SubAgentRun]] = {}
        for conversation_id, runs in conversations.items():
            if not isinstance(runs, dict):
                continue
            bucket: dict[str, SubAgentRun] = {}
            for run_id, payload in runs.items():
                run = self._deserialize_run(payload)
                if run is None:
                    continue
                bucket[run_id] = run
            if bucket:
                loaded[conversation_id] = bucket
        return loaded

    def _recover_inflight_runs(self) -> None:
        updated = False
        for _conversation_id, bucket in self._runs_by_conversation.items():
            for run_id, run in list(bucket.items()):
                if run.status not in self._ACTIVE_STATUSES:
                    continue
                recovered = run.time_out(reason="Recovered after process restart")
                recovered = replace(
                    recovered,
                    metadata={**recovered.metadata, "recovered_on_startup": True},
                )
                bucket[run_id] = recovered
                updated = True
        if updated:
            self._persist_locked()

    def _persist(self) -> None:
        if not self._persistence_path and self._repository is None:
            return
        if self._sync_across_processes:
            with self._with_registry_lock(exclusive=True):
                self._persist_locked()
            return
        self._persist_locked()

    def _persist_locked(self) -> None:
        if self._repository is not None:
            try:
                self._repository.save_runs(self._runs_by_conversation)
            except Exception as exc:
                logger.warning(f"[SubAgentRunRegistry] Failed to persist repository runs: {exc}")
            return
        if not self._persistence_path:
            return
        payload = {
            "version": self._PERSIST_VERSION,
            "conversations": {
                conversation_id: {run_id: run.to_event_data() for run_id, run in bucket.items()}
                for conversation_id, bucket in self._runs_by_conversation.items()
            },
        }
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persistence_path.with_suffix(f"{self._persistence_path.suffix}.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._persistence_path)
        except Exception as exc:
            logger.warning(f"[SubAgentRunRegistry] Failed to persist runs: {exc}")

    @staticmethod
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
            run = SubAgentRun(
                run_id=str(payload.get("run_id") or ""),
                conversation_id=str(payload.get("conversation_id") or ""),
                subagent_name=str(payload.get("subagent_name") or ""),
                task=str(payload.get("task") or ""),
                status=status,
                created_at=SubAgentRunRegistry._parse_datetime(payload.get("created_at"))
                or datetime.now(UTC),
                started_at=SubAgentRunRegistry._parse_datetime(payload.get("started_at")),
                ended_at=SubAgentRunRegistry._parse_datetime(payload.get("ended_at")),
                summary=SubAgentRunRegistry._optional_str(payload.get("summary")),
                error=SubAgentRunRegistry._optional_str(payload.get("error")),
                execution_time_ms=SubAgentRunRegistry._optional_int(
                    payload.get("execution_time_ms")
                ),
                tokens_used=SubAgentRunRegistry._optional_int(payload.get("tokens_used")),
                metadata=metadata,
            )
        except Exception:
            return None
        return run

    @staticmethod
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

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def close(self) -> None:
        """Release resources held by the underlying repository."""
        if self._repository is None:
            return
        close = getattr(self._repository, "close", None)
        if callable(close):
            close()
