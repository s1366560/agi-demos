"""Revisioned and idempotent contract helpers for HITL responses."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from src.domain.model.agent.hitl_request import HITLRequestStatus

HITL_PENDING_AUTHORITY_REVISION = 1
HITL_SETTLED_AUTHORITY_REVISION = 2
HITL_RESPONSE_CONTRACT_VERSION = 2

_CONTRACT_METADATA_KEY = "_hitl_response_contract"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[!-~]{1,255}$")
_HMAC_CONTEXT = b"memstack:hitl-response:v2"


@dataclass(frozen=True, slots=True)
class HitlResponseContractMetadata:
    """Persisted receipt used to classify safe response replays."""

    contract_version: int
    expected_revision: int
    idempotency_key: str
    payload_digest: str


def hitl_authority_revision(status: HITLRequestStatus | str) -> int:
    """Return the HITL-owned revision for a persisted request status."""
    value = status.value if isinstance(status, HITLRequestStatus) else status
    if value == HITLRequestStatus.PENDING.value:
        return HITL_PENDING_AUTHORITY_REVISION
    return HITL_SETTLED_AUTHORITY_REVISION


def build_hitl_response_digest(
    *,
    secret: str,
    request_id: str,
    hitl_type: str,
    response_data: Mapping[str, Any],
) -> str:
    """Return a keyed canonical digest without persisting response values."""
    if not secret:
        raise ValueError("HITL response digest secret must not be empty")
    payload = json.dumps(
        {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "response_data": response_data,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest_key = hmac.new(secret.encode("utf-8"), _HMAC_CONTEXT, hashlib.sha256).digest()
    return hmac.new(digest_key, payload, hashlib.sha256).hexdigest()


def merge_hitl_response_contract_metadata(
    response_metadata: Mapping[str, Any] | None,
    *,
    expected_revision: int,
    idempotency_key: str,
    payload_digest: str,
) -> dict[str, Any]:
    """Attach a validated V2 receipt while preserving sealed response metadata."""
    if expected_revision != HITL_PENDING_AUTHORITY_REVISION:
        raise ValueError("HITL response claims must target pending authority revision 1")
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("Invalid HITL response idempotency key")
    if not _DIGEST_PATTERN.fullmatch(payload_digest):
        raise ValueError("Invalid HITL response payload digest")

    metadata = dict(response_metadata or {})
    metadata[_CONTRACT_METADATA_KEY] = {
        "contract_version": HITL_RESPONSE_CONTRACT_VERSION,
        "expected_revision": expected_revision,
        "idempotency_key": idempotency_key,
        "payload_digest": payload_digest,
    }
    return metadata


def read_hitl_response_contract_metadata(
    response_metadata: object,
) -> HitlResponseContractMetadata | None:
    """Read a receipt only when every persisted protocol field is valid."""
    receipt: HitlResponseContractMetadata | None = None
    metadata: Mapping[str, Any] = (
        cast(Mapping[str, Any], response_metadata)
        if isinstance(response_metadata, Mapping)
        else cast(Mapping[str, Any], {})
    )
    raw_contract_candidate: Any = metadata.get(_CONTRACT_METADATA_KEY)
    raw_contract: Mapping[str, Any] = (
        cast(Mapping[str, Any], raw_contract_candidate)
        if isinstance(raw_contract_candidate, Mapping)
        else cast(Mapping[str, Any], {})
    )
    expected_fields = {
        "contract_version",
        "expected_revision",
        "idempotency_key",
        "payload_digest",
    }
    if set(raw_contract) == expected_fields:
        contract_version = raw_contract.get("contract_version")
        expected_revision = raw_contract.get("expected_revision")
        idempotency_key = raw_contract.get("idempotency_key")
        payload_digest = raw_contract.get("payload_digest")
        valid_receipt = (
            contract_version == HITL_RESPONSE_CONTRACT_VERSION
            and not isinstance(expected_revision, bool)
            and expected_revision == HITL_PENDING_AUTHORITY_REVISION
            and isinstance(idempotency_key, str)
            and _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is not None
            and isinstance(payload_digest, str)
            and _DIGEST_PATTERN.fullmatch(payload_digest) is not None
        )
        if valid_receipt:
            assert isinstance(idempotency_key, str)
            assert isinstance(payload_digest, str)
            receipt = HitlResponseContractMetadata(
                contract_version=HITL_RESPONSE_CONTRACT_VERSION,
                expected_revision=HITL_PENDING_AUTHORITY_REVISION,
                idempotency_key=idempotency_key,
                payload_digest=payload_digest,
            )
    return receipt


__all__ = [
    "HITL_PENDING_AUTHORITY_REVISION",
    "HITL_RESPONSE_CONTRACT_VERSION",
    "HITL_SETTLED_AUTHORITY_REVISION",
    "HitlResponseContractMetadata",
    "build_hitl_response_digest",
    "hitl_authority_revision",
    "merge_hitl_response_contract_metadata",
    "read_hitl_response_contract_metadata",
]
