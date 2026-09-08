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
        }
