"""Publication policy and readiness values for plugin protocol v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from src.domain.model.plugins.generated_v2 import ApplyStatusV2, PublicationStatusV2

PYTHON_API_DATA_PLANE_ID_V2 = "python-api-v2"
DEFAULT_ACK_DEADLINE_SECONDS_V2 = 30
MAX_ACK_DEADLINE_SECONDS_V2 = 86_400

_DATA_PLANE_ID_PATTERN_V2 = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,254}$")


@dataclass(frozen=True, kw_only=True)
class PlatformPluginPublicationPolicyV2:
    """Finite required data-plane roster and acknowledgement deadline."""

    required_data_plane_ids: tuple[str, ...]
    ack_deadline_seconds: int = DEFAULT_ACK_DEADLINE_SECONDS_V2

    def __post_init__(self) -> None:
        normalized = _normalize_data_plane_ids_v2(self.required_data_plane_ids)
        if not normalized:
            raise ValueError("plugin v2 publication requires at least one data plane")
        deadline = cast(object, self.ack_deadline_seconds)
        if isinstance(deadline, bool) or not isinstance(deadline, int):
            raise ValueError("plugin v2 ACK deadline must be an integer")
        if not 1 <= deadline <= MAX_ACK_DEADLINE_SECONDS_V2:
            raise ValueError("plugin v2 ACK deadline must be between 1 and 86400 seconds")
        object.__setattr__(self, "required_data_plane_ids", normalized)

    @classmethod
    def local_default(cls) -> PlatformPluginPublicationPolicyV2:
        """Return the explicit local/dev policy required by the protocol."""
        return cls(
            required_data_plane_ids=(PYTHON_API_DATA_PLANE_ID_V2,),
            ack_deadline_seconds=DEFAULT_ACK_DEADLINE_SECONDS_V2,
        )

    @classmethod
    def from_deployment(
        cls,
        *,
        environment: str,
        required_data_plane_ids: str,
        ack_deadline_seconds: int,
    ) -> PlatformPluginPublicationPolicyV2:
        """Build policy from a deployment template, failing closed in production."""
        declared = tuple(part.strip() for part in required_data_plane_ids.split(","))
        declared = tuple(part for part in declared if part)
        if environment.strip().casefold() in {"production", "prod"} and not declared:
            raise ValueError(
                "production plugin v2 publication requires an explicit required data-plane roster"
            )
        if not declared:
            declared = (PYTHON_API_DATA_PLANE_ID_V2,)
        return cls(
            required_data_plane_ids=declared,
            ack_deadline_seconds=ack_deadline_seconds,
        )

    def deadline_from(self, requested_at: datetime) -> datetime:
        """Return the immutable deadline for one newly recorded publication."""
        return requested_at + timedelta(seconds=self.ack_deadline_seconds)


@dataclass(frozen=True, kw_only=True)
class PlatformPluginDataPlaneReadinessV2:
    """Latest exact receipt for one required plane in a publication."""

    data_plane_id: str
    status: ApplyStatusV2 | None
    requested_version: int | None
    requested_digest: str | None
    applied_version: int | None
    applied_digest: str | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, kw_only=True)
class PlatformPluginPublicationReadinessV2:
    """Aggregated readiness for one immutable publication."""

    publication_id: str
    profile_id: str
    generation: int
    requested_version: int
    snapshot_digest: str
    nonce: str
    republished_from_nonce: str | None
    required_data_plane_ids: tuple[str, ...]
    ack_deadline_at: datetime
    status: PublicationStatusV2
    ready_at: datetime | None
    data_planes: tuple[PlatformPluginDataPlaneReadinessV2, ...]


def _normalize_data_plane_ids_v2(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not _DATA_PLANE_ID_PATTERN_V2.fullmatch(item):
            raise ValueError(f"invalid plugin v2 data_plane_id: {value!r}")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(normalized)


__all__ = [
    "DEFAULT_ACK_DEADLINE_SECONDS_V2",
    "MAX_ACK_DEADLINE_SECONDS_V2",
    "PYTHON_API_DATA_PLANE_ID_V2",
    "PlatformPluginDataPlaneReadinessV2",
    "PlatformPluginPublicationPolicyV2",
    "PlatformPluginPublicationReadinessV2",
]
