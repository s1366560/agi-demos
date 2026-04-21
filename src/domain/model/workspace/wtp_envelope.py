"""
Workspace Task Protocol (WTP) — message envelope and verb vocabulary.

WTP is a thin semantic layer that rides on top of the existing A2A transport
(``AgentMessageBusPort``). It does **not** introduce a new bus, stream layout,
or table; it only standardises the shape of ``AgentMessage.metadata`` and
``AgentMessage.content`` so leader ↔ worker interactions in a workspace are:

* Structured (every message has a machine-readable verb).
* Correlatable (``correlation_id`` groups request/response pairs).
* Routable (``workspace_id`` / ``task_id`` / ``attempt_id`` always present).
* Policy-checkable (the role matrix in §3.3 of the WTP architecture plan is
  expressed purely via :class:`WtpVerb`).

This module is pure domain — no Redis, no SQLAlchemy, no orchestrator import.
Infrastructure code constructs a :class:`WtpEnvelope`, renders it via
:meth:`WtpEnvelope.to_metadata` + :meth:`WtpEnvelope.to_content`, and hands
those to ``AgentOrchestrator.send_message``. On the receiving side, the
workspace supervisor restores the envelope via :meth:`WtpEnvelope.from_message`.

Reserved metadata keys (namespaced with ``wtp_`` or ``workspace_``):

* ``wtp_version``: protocol version string (currently ``"1"``).
* ``wtp_verb``: value of :class:`WtpVerb`.
* ``workspace_id``: UUID of the owning workspace.
* ``task_id``: UUID of the :class:`WorkspaceTask` the envelope refers to.
* ``attempt_id``: UUID of the :class:`WorkspaceTaskSessionAttempt` the envelope refers to.
* ``correlation_id``: UUID grouping a request/response pair (for clarifications).
* ``root_goal_task_id``: UUID of the root goal the task rolls up into (optional).

All other keys in ``metadata`` are considered user-defined and preserved
verbatim through roundtrips.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageType,
)


WTP_VERSION = "1"


class WtpVerb(str, Enum):
    """
    Canonical set of leader ↔ worker actions in a workspace.

    See §3.1 of the WTP architecture plan for the direction matrix. The
    leader→worker vs. worker→leader direction is NOT encoded in the verb
    itself (that's a policy concern); it is derived at the policy layer
    using :attr:`LEADER_TO_WORKER_VERBS` / :attr:`WORKER_TO_LEADER_VERBS`.
    """

    TASK_ASSIGN = "task.assign"
    TASK_REVISE = "task.revise"
    TASK_CANCEL = "task.cancel"
    TASK_CLARIFY_RESPONSE = "task.clarify_response"

    TASK_PROGRESS = "task.progress"
    TASK_CLARIFY_REQUEST = "task.clarify_request"
    TASK_COMPLETED = "task.completed"
    TASK_BLOCKED = "task.blocked"
    TASK_HEARTBEAT = "task.heartbeat"

    @classmethod
    def leader_to_worker(cls) -> frozenset[WtpVerb]:
        """Verbs that only the workspace leader may emit."""
        return frozenset(
            {
                cls.TASK_ASSIGN,
                cls.TASK_REVISE,
                cls.TASK_CANCEL,
                cls.TASK_CLARIFY_RESPONSE,
            }
        )

    @classmethod
    def worker_to_leader(cls) -> frozenset[WtpVerb]:
        """Verbs that only a non-leader workspace agent may emit."""
        return frozenset(
            {
                cls.TASK_PROGRESS,
                cls.TASK_CLARIFY_REQUEST,
                cls.TASK_COMPLETED,
                cls.TASK_BLOCKED,
                cls.TASK_HEARTBEAT,
            }
        )

    @classmethod
    def terminal(cls) -> frozenset[WtpVerb]:
        """Verbs that transition the attempt out of the running state."""
        return frozenset({cls.TASK_COMPLETED, cls.TASK_BLOCKED})

    @classmethod
    def request_verbs(cls) -> frozenset[WtpVerb]:
        """Verbs that expect a matching response keyed by ``correlation_id``."""
        return frozenset({cls.TASK_ASSIGN, cls.TASK_REVISE, cls.TASK_CLARIFY_REQUEST})

    def default_message_type(self) -> AgentMessageType:
        """The :class:`AgentMessageType` this verb ships as by default."""
        if self in {WtpVerb.TASK_ASSIGN, WtpVerb.TASK_REVISE, WtpVerb.TASK_CLARIFY_REQUEST}:
            return AgentMessageType.REQUEST
        if self is WtpVerb.TASK_CLARIFY_RESPONSE:
            return AgentMessageType.RESPONSE
        if self in WtpVerb.terminal():
            return AgentMessageType.ANNOUNCE
        return AgentMessageType.NOTIFICATION


class WtpValidationError(ValueError):
    """Raised when an :class:`WtpEnvelope` fails structural validation."""


# --- Payload-shape validation ----------------------------------------------
# Each verb declares the set of payload keys it REQUIRES. Extra keys are
# allowed (forward compatibility) but the required set MUST be present,
# non-empty, and of the expected scalar type where checked.

_REQUIRED_PAYLOAD_KEYS: dict[WtpVerb, frozenset[str]] = {
    WtpVerb.TASK_ASSIGN: frozenset({"title", "description"}),
    WtpVerb.TASK_REVISE: frozenset({"diff"}),
    WtpVerb.TASK_CANCEL: frozenset({"reason"}),
    WtpVerb.TASK_CLARIFY_RESPONSE: frozenset({"answer"}),
    WtpVerb.TASK_PROGRESS: frozenset({"summary"}),
    WtpVerb.TASK_CLARIFY_REQUEST: frozenset({"question"}),
    WtpVerb.TASK_COMPLETED: frozenset({"summary"}),
    WtpVerb.TASK_BLOCKED: frozenset({"reason"}),
    WtpVerb.TASK_HEARTBEAT: frozenset(),
}


@dataclass(kw_only=True)
class WtpEnvelope:
    """
    A structured Workspace Task Protocol message.

    The envelope is transport-agnostic: it knows how to serialise itself into
    an ``AgentMessage`` (``to_metadata`` + ``to_content``) and how to rehydrate
    itself from one (``from_message``).
    """

    verb: WtpVerb
    workspace_id: str
    task_id: str
    attempt_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    root_goal_task_id: str | None = None
    parent_message_id: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    # --- Validation ---------------------------------------------------------

    def validate(self) -> None:
        """
        Raise :class:`WtpValidationError` if the envelope is malformed.

        This is called automatically in ``__post_init__`` but is also safe to
        invoke after mutation.
        """
        if not isinstance(self.verb, WtpVerb):
            raise WtpValidationError(f"verb must be a WtpVerb, got {type(self.verb)!r}")
        for field_name in ("workspace_id", "task_id", "attempt_id", "correlation_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise WtpValidationError(f"{field_name} must be a non-empty string")
        if self.root_goal_task_id is not None and not isinstance(self.root_goal_task_id, str):
            raise WtpValidationError("root_goal_task_id must be a string or None")
        if not isinstance(self.payload, dict):
            raise WtpValidationError("payload must be a dict")
        if not isinstance(self.extra_metadata, dict):
            raise WtpValidationError("extra_metadata must be a dict")
        missing = _REQUIRED_PAYLOAD_KEYS[self.verb] - self.payload.keys()
        if missing:
            raise WtpValidationError(
                f"verb {self.verb.value!r} missing required payload keys: {sorted(missing)}"
            )
        # Required string payload keys must be non-empty strings where present.
        for key in _REQUIRED_PAYLOAD_KEYS[self.verb]:
            value = self.payload.get(key)
            if value is not None and not isinstance(value, (str, dict, list)):
                raise WtpValidationError(
                    f"payload[{key!r}] must be str/dict/list, got {type(value).__name__}"
                )
            if isinstance(value, str) and not value.strip():
                raise WtpValidationError(f"payload[{key!r}] must not be blank")

    # --- Serialisation ------------------------------------------------------

    def to_metadata(self) -> dict[str, Any]:
        """Render the envelope's metadata block (goes into ``AgentMessage.metadata``)."""
        meta: dict[str, Any] = dict(self.extra_metadata)
        meta.update(
            {
                "wtp_version": WTP_VERSION,
                "wtp_verb": self.verb.value,
                "workspace_id": self.workspace_id,
                "task_id": self.task_id,
                "attempt_id": self.attempt_id,
                "correlation_id": self.correlation_id,
            }
        )
        if self.root_goal_task_id is not None:
            meta["root_goal_task_id"] = self.root_goal_task_id
        return meta

    def to_content(self) -> str:
        """Render the envelope's content block (goes into ``AgentMessage.content``)."""
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        """Full dict representation (used by event pipeline + tests)."""
        return {
            "verb": self.verb.value,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "correlation_id": self.correlation_id,
            "root_goal_task_id": self.root_goal_task_id,
            "parent_message_id": self.parent_message_id,
            "payload": dict(self.payload),
            "extra_metadata": dict(self.extra_metadata),
        }

    # --- Deserialisation ---------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WtpEnvelope:
        """Inverse of :meth:`to_dict`."""
        try:
            verb = WtpVerb(data["verb"])
        except (KeyError, ValueError) as exc:
            raise WtpValidationError(f"invalid or missing verb: {data.get('verb')!r}") from exc
        return cls(
            verb=verb,
            workspace_id=data["workspace_id"],
            task_id=data["task_id"],
            attempt_id=data["attempt_id"],
            correlation_id=data.get("correlation_id") or str(uuid.uuid4()),
            root_goal_task_id=data.get("root_goal_task_id"),
            parent_message_id=data.get("parent_message_id"),
            payload=dict(data.get("payload") or {}),
            extra_metadata=dict(data.get("extra_metadata") or {}),
        )

    @classmethod
    def from_message(cls, message: AgentMessage) -> WtpEnvelope:
        """
        Rehydrate an envelope from a raw :class:`AgentMessage`.

        Raises :class:`WtpValidationError` if the message does not carry a WTP
        envelope (missing ``wtp_verb`` metadata).
        """
        metadata = dict(message.metadata or {})
        verb_str = metadata.pop("wtp_verb", None)
        if not verb_str:
            raise WtpValidationError("AgentMessage is not a WTP envelope: missing wtp_verb")
        try:
            verb = WtpVerb(verb_str)
        except ValueError as exc:
            raise WtpValidationError(f"unknown WTP verb: {verb_str!r}") from exc

        metadata.pop("wtp_version", None)
        workspace_id = metadata.pop("workspace_id", "") or ""
        task_id = metadata.pop("task_id", "") or ""
        attempt_id = metadata.pop("attempt_id", "") or ""
        correlation_id = metadata.pop("correlation_id", "") or str(uuid.uuid4())
        root_goal_task_id = metadata.pop("root_goal_task_id", None)

        try:
            payload = json.loads(message.content) if message.content else {}
        except json.JSONDecodeError as exc:
            raise WtpValidationError(f"WTP content is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise WtpValidationError(
                f"WTP content must decode to a dict, got {type(payload).__name__}"
            )

        return cls(
            verb=verb,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            correlation_id=correlation_id,
            root_goal_task_id=root_goal_task_id,
            parent_message_id=message.parent_message_id,
            payload=payload,
            extra_metadata=metadata,
        )

    # --- Convenience --------------------------------------------------------

    def default_message_type(self) -> AgentMessageType:
        """Delegate to :meth:`WtpVerb.default_message_type` for callers."""
        return self.verb.default_message_type()

    def is_terminal(self) -> bool:
        return self.verb in WtpVerb.terminal()


def is_wtp_message(message: AgentMessage) -> bool:
    """Cheap predicate: does the raw message carry a WTP envelope?"""
    if not message.metadata:
        return False
    return bool(message.metadata.get("wtp_verb"))


__all__ = [
    "WTP_VERSION",
    "WtpEnvelope",
    "WtpValidationError",
    "WtpVerb",
    "is_wtp_message",
]
