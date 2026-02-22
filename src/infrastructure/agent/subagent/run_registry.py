"""Registry for SubAgent run lifecycle tracking with optional persistence."""

import json
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus

logger = logging.getLogger(__name__)


class SubAgentRunRegistry:
    """Tracks delegated SubAgent runs grouped by conversation."""

    _ACTIVE_STATUSES = {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}
    _PERSIST_VERSION = 1

    def __init__(
        self,
        max_runs_per_conversation: int = 200,
        persistence_path: Optional[str] = None,
        terminal_retention_seconds: int = 86400,
        recover_inflight_on_boot: bool = True,
    ) -> None:
        self._runs_by_conversation: Dict[str, Dict[str, SubAgentRun]] = {}
        self._max_runs_per_conversation = max(1, max_runs_per_conversation)
        self._persistence_path = Path(persistence_path).expanduser() if persistence_path else None
        self._terminal_retention_seconds = max(0, terminal_retention_seconds)
        self._recover_inflight_on_boot = recover_inflight_on_boot
        self._load_from_disk()

    def create_run(
        self,
        conversation_id: str,
        subagent_name: str,
        task: str,
        metadata: Optional[Dict[str, object]] = None,
        run_id: Optional[str] = None,
        requester_session_key: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        lineage_root_run_id: Optional[str] = None,
    ) -> SubAgentRun:
        """Create and register a new pending run."""
        run_metadata = dict(metadata or {})
        if requester_session_key:
            run_metadata.setdefault("requester_session_key", requester_session_key)
        if parent_run_id:
            run_metadata.setdefault("parent_run_id", parent_run_id)
        if lineage_root_run_id:
            run_metadata.setdefault("lineage_root_run_id", lineage_root_run_id)

        run = SubAgentRun(
            run_id=run_id or uuid.uuid4().hex,
            conversation_id=conversation_id,
            subagent_name=subagent_name,
            task=task,
            metadata=run_metadata,
        )
        if not run.metadata.get("lineage_root_run_id"):
            run = replace(run, metadata={**run.metadata, "lineage_root_run_id": run.run_id})
        self._upsert(run)
        return run

    def mark_running(
        self,
        conversation_id: str,
        run_id: str,
        metadata: Optional[Dict[str, object]] = None,
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Transition run to RUNNING."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        try:
            running = run.start()
        except ValueError:
            return None
        if metadata:
            running = replace(running, metadata={**running.metadata, **metadata})
        return self._upsert(running)

    def mark_completed(
        self,
        conversation_id: str,
        run_id: str,
        summary: Optional[str] = None,
        tokens_used: Optional[int] = None,
        execution_time_ms: Optional[int] = None,
        metadata: Optional[Dict[str, object]] = None,
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Transition run to COMPLETED."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        try:
            completed = run.complete(
                summary=summary,
                tokens_used=tokens_used,
                execution_time_ms=execution_time_ms,
            )
        except ValueError:
            return None
        if metadata:
            completed = replace(completed, metadata={**completed.metadata, **metadata})
        return self._upsert(completed)

    def mark_failed(
        self,
        conversation_id: str,
        run_id: str,
        error: str,
        execution_time_ms: Optional[int] = None,
        metadata: Optional[Dict[str, object]] = None,
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Transition run to FAILED."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        try:
            failed = run.fail(error=error, execution_time_ms=execution_time_ms)
        except ValueError:
            return None
        if metadata:
            failed = replace(failed, metadata={**failed.metadata, **metadata})
        return self._upsert(failed)

    def mark_cancelled(
        self,
        conversation_id: str,
        run_id: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Transition run to CANCELLED."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        try:
            cancelled = run.cancel(reason=reason)
        except ValueError:
            return None
        if metadata:
            cancelled = replace(cancelled, metadata={**cancelled.metadata, **metadata})
        return self._upsert(cancelled)

    def mark_timed_out(
        self,
        conversation_id: str,
        run_id: str,
        reason: str = "SubAgent execution timed out",
        metadata: Optional[Dict[str, object]] = None,
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Transition run to TIMED_OUT."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        try:
            timed_out = run.time_out(reason=reason)
        except ValueError:
            return None
        if metadata:
            timed_out = replace(timed_out, metadata={**timed_out.metadata, **metadata})
        return self._upsert(timed_out)

    def attach_metadata(
        self,
        conversation_id: str,
        run_id: str,
        metadata: Dict[str, object],
        expected_statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> Optional[SubAgentRun]:
        """Merge metadata into a run."""
        run = self.get_run(conversation_id, run_id)
        if run is None:
            return None
        if expected_statuses and run.status not in set(expected_statuses):
            return None
        merged = dict(run.metadata)
        merged.update(metadata)
        return self._upsert(replace(run, metadata=merged))

    def get_run(self, conversation_id: str, run_id: str) -> Optional[SubAgentRun]:
        """Get one run by conversation + run id."""
        return self._runs_by_conversation.get(conversation_id, {}).get(run_id)

    def list_runs(
        self,
        conversation_id: str,
        statuses: Optional[Sequence[SubAgentRunStatus]] = None,
    ) -> List[SubAgentRun]:
        """List runs for a conversation in reverse chronological order."""
        runs = list(self._runs_by_conversation.get(conversation_id, {}).values())
        if statuses:
            allowed = set(statuses)
            runs = [run for run in runs if run.status in allowed]
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return runs

    def list_descendant_runs(
        self,
        conversation_id: str,
        parent_run_id: str,
        *,
        include_terminal: bool = True,
    ) -> List[SubAgentRun]:
        """List descendants of a run using metadata.parent_run_id."""
        bucket = self._runs_by_conversation.get(conversation_id, {})
        children_by_parent: Dict[str, List[SubAgentRun]] = {}
        for run in bucket.values():
            parent_id = str(run.metadata.get("parent_run_id") or "").strip()
            if not parent_id:
                continue
            children_by_parent.setdefault(parent_id, []).append(run)

        queue = [parent_run_id]
        visited: set[str] = set()
        descendants: List[SubAgentRun] = []
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
        return len(
            [
                run
                for run in self._runs_by_conversation.get(conversation_id, {}).values()
                if run.status in self._ACTIVE_STATUSES
            ]
        )

    def count_active_runs_for_requester(
        self,
        conversation_id: str,
        requester_session_key: str,
    ) -> int:
        """Count active runs scoped to a requester session key."""
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

    def _upsert(self, run: SubAgentRun) -> SubAgentRun:
        bucket = self._runs_by_conversation.setdefault(run.conversation_id, {})
        bucket[run.run_id] = run
        self._evict_if_needed(run.conversation_id)
        self._persist()
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
        threshold = datetime.now(timezone.utc) - timedelta(seconds=self._terminal_retention_seconds)
        for run in list(bucket.values()):
            if run.status in self._ACTIVE_STATUSES:
                continue
            ended_at = run.ended_at or run.created_at
            if ended_at <= threshold:
                bucket.pop(run.run_id, None)

    def _load_from_disk(self) -> None:
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

        loaded: Dict[str, Dict[str, SubAgentRun]] = {}
        for conversation_id, runs in conversations.items():
            if not isinstance(runs, dict):
                continue
            bucket: Dict[str, SubAgentRun] = {}
            for run_id, payload in runs.items():
                run = self._deserialize_run(payload)
                if run is None:
                    continue
                bucket[run_id] = run
            if bucket:
                loaded[conversation_id] = bucket
        self._runs_by_conversation = loaded

        if self._recover_inflight_on_boot:
            self._recover_inflight_runs()

    def _recover_inflight_runs(self) -> None:
        updated = False
        for conversation_id, bucket in self._runs_by_conversation.items():
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
            self._persist()

    def _persist(self) -> None:
        if not self._persistence_path:
            return
        payload = {
            "version": self._PERSIST_VERSION,
            "conversations": {
                conversation_id: {
                    run_id: run.to_event_data() for run_id, run in bucket.items()
                }
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
    def _deserialize_run(payload: Any) -> Optional[SubAgentRun]:
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
                or datetime.now(timezone.utc),
                started_at=SubAgentRunRegistry._parse_datetime(payload.get("started_at")),
                ended_at=SubAgentRunRegistry._parse_datetime(payload.get("ended_at")),
                summary=SubAgentRunRegistry._optional_str(payload.get("summary")),
                error=SubAgentRunRegistry._optional_str(payload.get("error")),
                execution_time_ms=SubAgentRunRegistry._optional_int(payload.get("execution_time_ms")),
                tokens_used=SubAgentRunRegistry._optional_int(payload.get("tokens_used")),
                metadata=metadata,
            )
        except Exception:
            return None
        return run

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
