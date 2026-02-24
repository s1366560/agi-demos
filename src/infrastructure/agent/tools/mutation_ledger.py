"""Persistent mutation audit ledger for self-modifying tool operations."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


class MutationLedger:
    """Store mutation audit records and evaluate repeated-fingerprint loop guards."""

    def __init__(
        self,
        ledger_path: Path | None = None,
        *,
        max_records: int = 2000,
    ) -> None:
        root = Path.cwd()
        self._ledger_path = ledger_path or (root / ".memstack" / "plugins" / "mutation_ledger.json")
        self._lock_path = self._ledger_path.with_suffix(f"{self._ledger_path.suffix}.lock")
        self._max_records = max(100, int(max_records))
        self._lock = RLock()

    @property
    def ledger_path(self) -> Path:
        """Return persisted ledger path."""
        return self._ledger_path

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Append one audit record to ledger and return normalized payload."""
        with self._lock, self._with_file_lock(exclusive=True):
            records = self._read_records()
            normalized = self._normalize_record(record)
            records.append(normalized)
            if len(records) > self._max_records:
                records = records[-self._max_records :]
            self._write_records(records)
            return dict(normalized)

    def evaluate_loop_guard(
        self,
        fingerprint: str,
        *,
        threshold: int,
        window_seconds: int,
    ) -> dict[str, Any]:
        """Evaluate whether repeated fingerprint should be blocked."""
        normalized_fingerprint = (fingerprint or "").strip()
        safe_threshold = max(1, int(threshold))
        safe_window_seconds = max(1, int(window_seconds))
        if not normalized_fingerprint:
            return {
                "blocked": False,
                "recent_count": 0,
                "threshold": safe_threshold,
                "window_seconds": safe_window_seconds,
                "last_seen_at": None,
            }

        now = datetime.now(UTC)
        since = now - timedelta(seconds=safe_window_seconds)
        with self._lock, self._with_file_lock(exclusive=False):
            records = self._read_records()

        matched: list[dict[str, Any]] = []
        for item in records:
            if str(item.get("mutation_fingerprint") or "") != normalized_fingerprint:
                continue
            if str(item.get("status") or "") == "dry_run":
                continue
            parsed = _parse_iso_datetime(item.get("timestamp"))
            if parsed and parsed >= since:
                matched.append(item)

        matched.sort(key=lambda item: str(item.get("timestamp") or ""))
        recent_count = len(matched)
        blocked = recent_count >= safe_threshold
        last_seen_at = matched[-1].get("timestamp") if matched else None
        return {
            "blocked": blocked,
            "recent_count": recent_count,
            "threshold": safe_threshold,
            "window_seconds": safe_window_seconds,
            "last_seen_at": last_seen_at,
        }

    def _read_records(self) -> list[dict[str, Any]]:
        if not self._ledger_path.exists():
            return []
        try:
            raw = self._ledger_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        records: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                records.append(dict(item))
        return records

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._ledger_path.with_suffix(f"{self._ledger_path.suffix}.tmp")
        payload = json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self._ledger_path)

    @contextmanager
    def _with_file_lock(self, *, exclusive: bool) -> Iterator[None]:
        if fcntl is None:
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

    @staticmethod
    def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        parsed_timestamp = _parse_iso_datetime(payload.get("timestamp"))
        payload["timestamp"] = (
            parsed_timestamp or datetime.now(UTC)
        ).astimezone(UTC).isoformat()
        return payload


@lru_cache(maxsize=1)
def get_mutation_ledger() -> MutationLedger:
    """Return process-wide mutation ledger singleton."""
    return MutationLedger()


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
