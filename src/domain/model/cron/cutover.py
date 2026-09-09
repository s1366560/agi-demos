"""Structural deployment evidence for a fail-closed scheduler handover."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, cast


class CronCutoverPhase(StrEnum):
    UNVERIFIED = "unverified"
    PREPARED = "prepared"
    BLOCKED = "blocked"
    VERIFIED = "verified"


class CronCutoverDrainDirection(StrEnum):
    FORWARD = "forward"
    REVERSE = "reverse"


# Terminal run outcomes the durable scheduler projector can record. Membership is a
# structural protocol fact shared with the execution plane, not a judgment.
CRON_RUN_TERMINAL_OUTCOMES = frozenset({"success", "failed", "timeout", "cancelled", "skipped"})


class CronDeploymentParticipantKind(StrEnum):
    PRODUCER = "producer"
    QUEUE = "queue"
    EXECUTION = "execution"
    HITL_RESUME = "hitl_resume"


class CronDeploymentObservation(StrEnum):
    CLOSED = "closed"
    UNRESOLVED = "unresolved"


def _record(value: object, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid cron deployment evidence fields")
    if set(cast(Mapping[object, object], value)) != fields:
        raise ValueError("invalid cron deployment evidence fields")
    return cast(Mapping[str, object], value)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError("invalid cron deployment identity")
    return value


@dataclass(frozen=True, kw_only=True)
class CronDeploymentParticipant:
    kind: CronDeploymentParticipantKind
    participant_id: str

    def to_wire(self) -> dict[str, str]:
        return {"kind": self.kind.value, "participant_id": self.participant_id}

    @classmethod
    def from_wire(cls, value: object) -> Self:
        record = _record(value, {"kind", "participant_id"})
        return cls(
            kind=CronDeploymentParticipantKind(_identifier(record["kind"])),
            participant_id=_identifier(record["participant_id"]),
        )


@dataclass(frozen=True, kw_only=True)
class CronDeploymentManifest:
    """Declared roster to be verified against the real deployment control plane."""

    deployment_id: str
    source_generation: str
    target_generation: str
    participants: tuple[CronDeploymentParticipant, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": "cron-deployment-inventory.v1",
            "deployment_id": self.deployment_id,
            "source_generation": self.source_generation,
            "target_generation": self.target_generation,
            "participants": [participant.to_wire() for participant in self.participants],
        }

    @classmethod
    def from_wire(cls, value: object) -> Self:
        record = _record(
            value,
            {"protocol", "deployment_id", "source_generation", "target_generation", "participants"},
        )
        if record["protocol"] != "cron-deployment-inventory.v1":
            raise ValueError("invalid cron deployment inventory protocol")
        entries = record["participants"]
        if not isinstance(entries, list):
            raise ValueError("invalid cron deployment participant roster")
        values = cast(list[object], entries)
        if not values or len(values) > 1000:
            raise ValueError("invalid cron deployment participant roster")
        participants = tuple(CronDeploymentParticipant.from_wire(item) for item in values)
        if len(set(participants)) != len(participants):
            raise ValueError("duplicate cron deployment participant")
        return cls(
            deployment_id=_identifier(record["deployment_id"]),
            source_generation=_identifier(record["source_generation"]),
            target_generation=_identifier(record["target_generation"]),
            participants=participants,
        )


@dataclass(frozen=True, kw_only=True)
class CronDeploymentReceipt:
    """Unverified observation with a digest; no raw logs, secrets, or enable flags."""

    receipt_id: str
    deployment_id: str
    source_generation: str
    participant: CronDeploymentParticipant
    observation: CronDeploymentObservation
    evidence_sha256: str

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": "cron-deployment-drain-receipt.v1",
            "receipt_id": self.receipt_id,
            "deployment_id": self.deployment_id,
            "source_generation": self.source_generation,
            "participant": self.participant.to_wire(),
            "observation": self.observation.value,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_wire(cls, value: object) -> Self:
        record = _record(
            value,
            {
                "protocol",
                "receipt_id",
                "deployment_id",
                "source_generation",
                "participant",
                "observation",
                "evidence_sha256",
            },
        )
        if record["protocol"] != "cron-deployment-drain-receipt.v1":
            raise ValueError("invalid cron deployment receipt protocol")
        digest = _identifier(record["evidence_sha256"])
        if len(digest) != 64 or not set(digest).issubset("0123456789abcdef"):
            raise ValueError("invalid cron deployment evidence digest")
        return cls(
            receipt_id=_identifier(record["receipt_id"]),
            deployment_id=_identifier(record["deployment_id"]),
            source_generation=_identifier(record["source_generation"]),
            participant=CronDeploymentParticipant.from_wire(record["participant"]),
            observation=CronDeploymentObservation(_identifier(record["observation"])),
            evidence_sha256=digest,
        )


def _count_map(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid cron reverse drain counts")
    entries = cast(Mapping[object, object], value)
    if len(entries) > 64:
        raise ValueError("invalid cron reverse drain counts")
    counts: list[tuple[str, int]] = []
    for name, count in entries.items():
        counts.append((_identifier(name), _count(count)))
    return tuple(sorted(counts))


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid cron reverse drain count")
    return value


@dataclass(frozen=True, kw_only=True)
class CronReverseDrainObservation:
    """Durable reverse-drain record: open counts, drained outcomes, last run ids.

    Diagnostics recorded for operator verification; never an activation switch.
    """

    counts: tuple[tuple[str, int], ...]
    terminal_outcomes: tuple[tuple[str, int], ...]
    last_run_ids: tuple[str, ...]
    observed_at: str

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": "cron-reverse-drain-observation.v1",
            "counts": dict(self.counts),
            "terminal_outcomes": dict(self.terminal_outcomes),
            "last_run_ids": list(self.last_run_ids),
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_wire(cls, value: object) -> Self:
        record = _record(
            value, {"protocol", "counts", "terminal_outcomes", "last_run_ids", "observed_at"}
        )
        if record["protocol"] != "cron-reverse-drain-observation.v1":
            raise ValueError("invalid cron reverse drain observation protocol")
        terminal_outcomes = _count_map(record["terminal_outcomes"])
        unknown = {name for name, _ in terminal_outcomes} - CRON_RUN_TERMINAL_OUTCOMES
        if unknown:
            raise ValueError("invalid cron reverse drain terminal outcome")
        run_ids = record["last_run_ids"]
        if not isinstance(run_ids, list):
            raise ValueError("invalid cron reverse drain run id roster")
        values = cast(list[object], run_ids)
        if len(values) > 100 or len(set(values)) != len(values):
            raise ValueError("invalid cron reverse drain run id roster")
        return cls(
            counts=_count_map(record["counts"]),
            terminal_outcomes=terminal_outcomes,
            last_run_ids=tuple(_identifier(item) for item in values),
            observed_at=_identifier(record["observed_at"]),
        )


@dataclass(frozen=True, kw_only=True)
class CronReverseDrainCompletion:
    """Rollback record appended only after a settled reverse drain re-admits Python."""

    completed_at: str
    final_observation: CronReverseDrainObservation

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": "cron-reverse-drain-completion.v1",
            "completed_at": self.completed_at,
            "final_observation": self.final_observation.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: object) -> Self:
        record = _record(value, {"protocol", "completed_at", "final_observation"})
        if record["protocol"] != "cron-reverse-drain-completion.v1":
            raise ValueError("invalid cron reverse drain completion protocol")
        return cls(
            completed_at=_identifier(record["completed_at"]),
            final_observation=CronReverseDrainObservation.from_wire(record["final_observation"]),
        )


@dataclass(frozen=True, kw_only=True)
class CronCutoverSnapshot:
    phase: CronCutoverPhase
    revision: int
    owner_kind: str
    deployment_id: str | None
    blockers: tuple[str, ...]
    observed_counts: tuple[tuple[str, int], ...] = ()
    receipts_recorded: int = 0
    observed_at: str | None = None
    drain_direction: CronCutoverDrainDirection | None = None
    terminal_outcomes: tuple[tuple[str, int], ...] = ()
    last_run_ids: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "revision": self.revision,
            "owner_kind": self.owner_kind,
            "deployment_id": self.deployment_id,
            "blockers": list(self.blockers),
            "observed_counts": dict(self.observed_counts),
            "receipts_recorded": self.receipts_recorded,
            "observed_at": self.observed_at,
            "drain_direction": self.drain_direction.value if self.drain_direction else None,
            "terminal_outcomes": dict(self.terminal_outcomes),
            "last_run_ids": list(self.last_run_ids),
        }
