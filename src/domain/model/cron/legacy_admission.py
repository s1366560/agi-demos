"""Process-safe identity for an admitted legacy scheduler execution."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Self


@dataclass(frozen=True, kw_only=True)
class LegacyCronAdmissionIdentity:
    """An opaque capability whose complete scope is verified against persistence."""

    admission_id: str
    tenant_id: str
    project_id: str
    job_id: str
    run_id: str
    message_id: str
    conversation_id: str
    owner_epoch: int
    token: str = field(repr=False)

    @property
    def token_hash(self) -> str:
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()

    def to_wire(self) -> dict[str, str | int]:
        return asdict(self)

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> Self:
        string_fields = (
            "admission_id",
            "tenant_id",
            "project_id",
            "job_id",
            "run_id",
            "message_id",
            "conversation_id",
            "token",
        )
        if set(value) != {*string_fields, "owner_epoch"}:
            raise ValueError("invalid legacy admission identity fields")
        strings: dict[str, str] = {}
        for name in string_fields:
            item = value[name]
            if not isinstance(item, str) or not item.strip():
                raise ValueError("invalid legacy admission identity value")
            strings[name] = item
        epoch = value["owner_epoch"]
        if type(epoch) is not int or epoch < 0:
            raise ValueError("invalid legacy admission epoch")
        return cls(owner_epoch=epoch, **strings)

    def matches_request(
        self, *, tenant_id: str, project_id: str, conversation_id: str, message_id: str
    ) -> bool:
        return (
            self.tenant_id == tenant_id
            and self.project_id == project_id
            and self.conversation_id == conversation_id
            and self.message_id == message_id
        )


@dataclass(frozen=True, kw_only=True)
class LegacyCronExecutionTicket:
    """One execution phase; a stale initial/resume delivery cannot settle a later phase."""

    admission: LegacyCronAdmissionIdentity
    nonce: str = field(repr=False)
