"""Trace digest — compact summary of a parent agent run injected into subagents.

Distilled from routa's `trace-run-digest.ts`. Solves the "cold start" problem
for delegated specialists: the child sees what files were touched, which
tools were called (and which failed), what verification commands ran, and
whether any churn signal was observed.

This module is the **pure value object + builder**. The caller is responsible
for fetching trace records (typically from Redis Streams or the trace DB).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.domain.shared_kernel import ValueObject


class TraceEventKind(str, Enum):
    """A structural classification of one trace event."""

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THOUGHT = "thought"
    ERROR = "error"
    OTHER = "other"


@dataclass(frozen=True, kw_only=True)
class TraceEvent(ValueObject):
    """Minimal structured shape of a trace record for digesting.

    Extra adapter-specific fields (raw payload, conversation_id, ...) are
    stripped before reaching this layer.
    """

    kind: TraceEventKind
    timestamp: datetime
    tool_name: str | None = None
    """For TOOL_CALL/TOOL_RESULT events."""
    success: bool | None = None
    """For TOOL_RESULT events."""
    file_path: str | None = None
    """File touched, if the event references one."""
    operation: str | None = None
    """Operation type (read / write / create / delete)."""
    summary: str | None = None
    """Short human-readable summary for THOUGHT and ERROR events."""


@dataclass(frozen=True, kw_only=True)
class FileDigestEntry(ValueObject):
    path: str
    operations: tuple[str, ...]
    touch_count: int


@dataclass(frozen=True, kw_only=True)
class ToolDigestEntry(ValueObject):
    name: str
    count: int
    failures: int


@dataclass(frozen=True, kw_only=True)
class VerificationSignal(ValueObject):
    command: str
    passed: bool
    summary: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChurnEntry(ValueObject):
    """High-churn marker: file or tool touched ≥ ``CHURN_THRESHOLD`` times."""

    target: str
    target_type: str  # "file" | "tool"
    count: int


@dataclass(frozen=True, kw_only=True)
class TraceRunDigest(ValueObject):
    """Compact run digest — the value injected into a subagent's prompt."""

    session_id: str
    total_events: int
    files_touched: tuple[FileDigestEntry, ...] = field(default_factory=tuple)
    tool_calls: tuple[ToolDigestEntry, ...] = field(default_factory=tuple)
    error_count: int = 0
    error_summaries: tuple[str, ...] = field(default_factory=tuple)
    key_thoughts: tuple[str, ...] = field(default_factory=tuple)
    time_range: tuple[datetime, datetime] | None = None
    verification_signals: tuple[VerificationSignal, ...] = field(default_factory=tuple)
    churn_markers: tuple[ChurnEntry, ...] = field(default_factory=tuple)
    confidence_flags: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """Compact prompt-ready Markdown block. Empty digest returns ``''``."""
        if self.total_events == 0:
            return ""
        lines: list[str] = ["[Parent Run Digest]", self._render_window()]
        lines.extend(self._render_files())
        lines.extend(self._render_tools())
        lines.extend(self._render_verifications())
        lines.extend(self._render_errors())
        lines.extend(self._render_churn())
        lines.extend(self._render_thoughts())
        lines.extend(self._render_flags())
        return "\n".join(lines)

    def _render_window(self) -> str:
        if self.time_range is None:
            return f"Events: {self.total_events}"
        start, end = self.time_range
        return (
            f"Window: {start.isoformat(timespec='seconds')} — "
            f"{end.isoformat(timespec='seconds')} "
            f"({self.total_events} events)"
        )

    def _render_files(self) -> list[str]:
        if not self.files_touched:
            return []
        out = ["Files touched:"]
        for entry in self.files_touched[:8]:
            ops = "/".join(entry.operations) or "?"
            out.append(f"  - {entry.path} [{ops}] x{entry.touch_count}")
        return out

    def _render_tools(self) -> list[str]:
        if not self.tool_calls:
            return []
        out = ["Tools used:"]
        for tool in self.tool_calls[:8]:
            if tool.failures:
                out.append(f"  - {tool.name} ({tool.count} calls, {tool.failures} failures)")
            else:
                out.append(f"  - {tool.name} ({tool.count} calls)")
        return out

    def _render_verifications(self) -> list[str]:
        if not self.verification_signals:
            return []
        out = ["Verification:"]
        for sig in self.verification_signals[:4]:
            tag = "PASS" if sig.passed else "FAIL"
            out.append(f"  - [{tag}] {sig.command}")
        return out

    def _render_errors(self) -> list[str]:
        if not self.error_summaries:
            return []
        out = [f"Errors ({self.error_count}):"]
        for summary in self.error_summaries[:5]:
            out.append(f"  - {summary}")
        return out

    def _render_churn(self) -> list[str]:
        if not self.churn_markers:
            return []
        out = ["Churn:"]
        for marker in self.churn_markers[:5]:
            out.append(f"  - {marker.target_type}:{marker.target} x{marker.count}")
        return out

    def _render_thoughts(self) -> list[str]:
        if not self.key_thoughts:
            return []
        out = ["Key thoughts:"]
        for thought in self.key_thoughts[:3]:
            out.append(f"  - {thought}")
        return out

    def _render_flags(self) -> list[str]:
        if not self.confidence_flags:
            return []
        out = ["Confidence flags:"]
        for flag in self.confidence_flags:
            out.append(f"  - {flag}")
        return out


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

#: A file/tool touched ≥ this many times in one run is flagged as churn.
CHURN_THRESHOLD = 3

#: Tool names that *can* run a verification step.
VERIFICATION_TOOL_NAMES = frozenset(
    {"run_command", "execute_command", "run_terminal", "bash", "shell", "terminal"}
)

#: Substrings that suggest a verification command in tool input/output.
VERIFICATION_CMD_KEYWORDS = (
    "test",
    "vitest",
    "jest",
    "pytest",
    "cargo test",
    "npm test",
    "check",
    "lint",
    "eslint",
    "tsc",
    "build",
    "compile",
    "verify",
    "validate",
)


def build_trace_run_digest(
    *, session_id: str, events: list[TraceEvent]
) -> TraceRunDigest:
    """Build a digest from a list of structured trace events. Pure function."""
    if not events:
        return TraceRunDigest(session_id=session_id, total_events=0)

    sorted_events = sorted(events, key=lambda e: e.timestamp)
    time_range = (sorted_events[0].timestamp, sorted_events[-1].timestamp)

    files_touched = _aggregate_files(sorted_events)
    tool_calls = _aggregate_tools(sorted_events)
    error_count, error_summaries = _aggregate_errors(sorted_events)
    key_thoughts = _collect_key_thoughts(sorted_events)
    verification_signals = _detect_verification(sorted_events)
    churn_markers = _detect_churn(files_touched, tool_calls)
    confidence_flags = _confidence_flags(error_count, churn_markers, verification_signals)

    return TraceRunDigest(
        session_id=session_id,
        total_events=len(sorted_events),
        files_touched=files_touched,
        tool_calls=tool_calls,
        error_count=error_count,
        error_summaries=error_summaries,
        key_thoughts=key_thoughts,
        time_range=time_range,
        verification_signals=verification_signals,
        churn_markers=churn_markers,
        confidence_flags=confidence_flags,
    )


def _aggregate_files(events: list[TraceEvent]) -> tuple[FileDigestEntry, ...]:
    ops_by_path: dict[str, set[str]] = {}
    count_by_path: dict[str, int] = {}
    for ev in events:
        if not ev.file_path:
            continue
        ops_by_path.setdefault(ev.file_path, set())
        if ev.operation:
            ops_by_path[ev.file_path].add(ev.operation)
        count_by_path[ev.file_path] = count_by_path.get(ev.file_path, 0) + 1

    entries = [
        FileDigestEntry(
            path=path,
            operations=tuple(sorted(ops_by_path[path])),
            touch_count=count_by_path[path],
        )
        for path in count_by_path
    ]
    entries.sort(key=lambda e: e.touch_count, reverse=True)
    return tuple(entries)


def _aggregate_tools(events: list[TraceEvent]) -> tuple[ToolDigestEntry, ...]:
    calls_by_name: dict[str, int] = {}
    failures_by_name: dict[str, int] = {}
    for ev in events:
        if ev.kind not in (TraceEventKind.TOOL_CALL, TraceEventKind.TOOL_RESULT):
            continue
        if not ev.tool_name:
            continue
        calls_by_name.setdefault(ev.tool_name, 0)
        failures_by_name.setdefault(ev.tool_name, 0)
        if ev.kind is TraceEventKind.TOOL_CALL:
            calls_by_name[ev.tool_name] += 1
        elif ev.kind is TraceEventKind.TOOL_RESULT and ev.success is False:
            failures_by_name[ev.tool_name] += 1

    entries = [
        ToolDigestEntry(name=name, count=calls_by_name[name], failures=failures_by_name[name])
        for name in calls_by_name
    ]
    entries.sort(key=lambda e: e.count, reverse=True)
    return tuple(entries)


def _aggregate_errors(events: list[TraceEvent]) -> tuple[int, tuple[str, ...]]:
    summaries: list[str] = []
    count = 0
    for ev in events:
        if ev.kind is TraceEventKind.ERROR or (ev.kind is TraceEventKind.TOOL_RESULT and ev.success is False):
            count += 1
            if ev.summary:
                summaries.append(ev.summary[:200])
    return count, tuple(summaries[:5])


def _collect_key_thoughts(events: list[TraceEvent]) -> tuple[str, ...]:
    thoughts = [ev.summary for ev in events if ev.kind is TraceEventKind.THOUGHT and ev.summary]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in thoughts:
        if t in seen:
            continue
        seen.add(t)
        deduped.append(t[:240])
        if len(deduped) >= 6:
            break
    return tuple(deduped[-3:])  # last 3 — most recent thinking


def _detect_verification(events: list[TraceEvent]) -> tuple[VerificationSignal, ...]:
    signals: list[VerificationSignal] = []
    pending_command: dict[str, str] = {}
    for ev in events:
        is_terminal_tool = ev.tool_name in VERIFICATION_TOOL_NAMES if ev.tool_name else False
        if not is_terminal_tool:
            continue
        if ev.kind is TraceEventKind.TOOL_CALL and ev.summary:
            cmd = ev.summary.lower()
            if any(kw in cmd for kw in VERIFICATION_CMD_KEYWORDS):
                pending_command[ev.tool_name or ""] = ev.summary[:120]
        elif ev.kind is TraceEventKind.TOOL_RESULT:
            cmd = pending_command.pop(ev.tool_name or "", None)
            if cmd is None:
                continue
            signals.append(
                VerificationSignal(
                    command=cmd,
                    passed=ev.success is not False,
                    summary=ev.summary[:200] if ev.summary else None,
                )
            )
    return tuple(signals)


def _detect_churn(
    files: tuple[FileDigestEntry, ...],
    tools: tuple[ToolDigestEntry, ...],
) -> tuple[ChurnEntry, ...]:
    out: list[ChurnEntry] = []
    for f in files:
        if f.touch_count >= CHURN_THRESHOLD:
            out.append(ChurnEntry(target=f.path, target_type="file", count=f.touch_count))
    for t in tools:
        if t.count >= CHURN_THRESHOLD and t.failures > 0:
            out.append(ChurnEntry(target=t.name, target_type="tool", count=t.count))
    out.sort(key=lambda c: c.count, reverse=True)
    return tuple(out)


def _confidence_flags(
    error_count: int,
    churn: tuple[ChurnEntry, ...],
    verifications: tuple[VerificationSignal, ...],
) -> tuple[str, ...]:
    flags: list[str] = []
    if error_count >= 3:
        flags.append(f"{error_count} errors observed in parent run")
    if any(c.target_type == "tool" for c in churn):
        flags.append("repeated tool failures (churn)")
    if any(not v.passed for v in verifications):
        flags.append("at least one verification command failed")
    return tuple(flags)


__all__ = [
    "CHURN_THRESHOLD",
    "ChurnEntry",
    "FileDigestEntry",
    "ToolDigestEntry",
    "TraceEvent",
    "TraceEventKind",
    "TraceRunDigest",
    "VerificationSignal",
    "build_trace_run_digest",
]
