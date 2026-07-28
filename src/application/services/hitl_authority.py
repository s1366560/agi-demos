"""Protocol-level authority snapshots for competing HITL responses."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus

HITLAuthorityReasonCode = Literal[
    "hitl_already_answered",
    "hitl_request_expired",
    "hitl_claim_conflict",
]

_ANSWERED_STATUSES = frozenset(
    {
        HITLRequestStatus.ANSWERED,
        HITLRequestStatus.PROCESSING,
        HITLRequestStatus.COMPLETED,
    }
)


@dataclass
class HitlAuthorityConflict(Exception):
    """Structured conflict returned when a HITL response does not win authority."""

    reason_code: HITLAuthorityReasonCode
    status_code: int
    detail: str
    authority_revision: int
    authority_status: str
    created_at: datetime
    answered_at: datetime | None
    expires_at: datetime | None
    observed_at: datetime

    def __post_init__(self) -> None:
        super().__init__(self.detail)

    def payload(self) -> dict[str, Any]:
        """Return the stable HTTP/WS error payload without response contents."""
        return {
            "detail": self.detail,
            "reason_code": self.reason_code,
            "authority_revision": self.authority_revision,
            "authority_status": self.authority_status,
            "created_at": self.created_at.isoformat(),
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "observed_at": self.observed_at.isoformat(),
        }


def classify_hitl_authority_conflict(
    hitl_request: HITLRequest,
    *,
    observed_at: datetime | None = None,
) -> HitlAuthorityConflict:
    """Classify a failed response claim from persisted protocol state."""
    now = observed_at or datetime.now(UTC)
    status = hitl_request.status
    if status in _ANSWERED_STATUSES:
        reason_code: HITLAuthorityReasonCode = "hitl_already_answered"
        status_code = 409
        detail = "HITL request is no longer pending"
        authority_status = status.value
        authority_revision = 2
    elif status == HITLRequestStatus.TIMEOUT or (
        status == HITLRequestStatus.PENDING
        and hitl_request.expires_at is not None
        and hitl_request.expires_at <= now
    ):
        reason_code = "hitl_request_expired"
        status_code = 410
        detail = "HITL request has expired"
        authority_status = HITLRequestStatus.TIMEOUT.value
        authority_revision = 2
    else:
        reason_code = "hitl_claim_conflict"
        status_code = 409
        detail = "HITL request could not be updated"
        authority_status = status.value
        authority_revision = 1 if status == HITLRequestStatus.PENDING else 2

    return HitlAuthorityConflict(
        reason_code=reason_code,
        status_code=status_code,
        detail=detail,
        authority_revision=authority_revision,
        authority_status=authority_status,
        created_at=hitl_request.created_at,
        answered_at=hitl_request.answered_at,
        expires_at=hitl_request.expires_at,
        observed_at=now,
    )


__all__ = [
    "HITLAuthorityReasonCode",
    "HitlAuthorityConflict",
    "classify_hitl_authority_conflict",
]
