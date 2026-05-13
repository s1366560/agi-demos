"""Actor identity value object — distinguishes user vs agent callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ActorIdentity:
    """Who is acting on a workspace resource.

    Used to attribute creation / mutation events to either a human user
    or an autonomous agent. Membership/permission checks are still performed
    against the human user that owns the credential — agents act under the
    user's authority.
    """

    kind: Literal["user", "agent"]
    id: str
    label: str

    def __post_init__(self) -> None:
        if self.kind not in ("user", "agent"):
            raise ValueError(f"invalid actor kind: {self.kind}")
        if not self.id:
            raise ValueError("actor id cannot be empty")
        if not self.label:
            raise ValueError("actor label cannot be empty")
