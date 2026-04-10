"""Structured denial payloads for agent-to-agent message send failures.

Provides a canonical denial-code enum, a structured SendDenied payload,
and a denial-code mapper that translates orchestrator ValueError messages
into machine-readable denial contracts consumed by the agent_send tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class SendDeniedCode(StrEnum):
    """Exhaustive denial codes for agent_send failures.

    Each code maps to one deterministic trigger condition in the
    orchestrator's send_message validation path.
    """

    SENDER_NOT_FOUND = "sender_not_found"
    SENDER_DISABLED = "sender_disabled"
    SENDER_A2A_DISABLED = "sender_a2a_disabled"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_DISABLED = "target_disabled"
    TARGET_A2A_DISABLED = "target_a2a_disabled"
    TARGET_NOT_ALLOWED = "target_not_allowed"
    SENDER_SESSION_REQUIRED = "sender_session_required"
    SENDER_SESSION_MISMATCH = "sender_session_mismatch"
    PROJECT_ID_REQUIRED = "project_id_required"
    TARGET_SESSION_NOT_FOUND = "target_session_not_found"
    TARGET_SESSION_MISMATCH = "target_session_mismatch"
    TARGET_ACTIVE_SESSION_MISSING = "target_active_session_missing"


@dataclass(frozen=True)
class SendDenied:
    """Structured denial payload returned by agent_send on every failure path.

    Fields
    ------
    ok: Always ``False`` for denials.
    code: One of the :class:`SendDeniedCode` values, deterministically set
        from the exact failure branch in the orchestrator.
    message: Human-readable explanation of the denial.
    from_agent_ref: Raw sender reference passed to the tool.
    to_agent_ref: Raw target reference passed to the tool.
    resolved_from_agent_id: Resolved sender agent ID, or ``None`` if sender
        resolution failed.
    resolved_to_agent_id: Resolved target agent ID, or ``None`` if target
        resolution failed.
    sender_session_id: The caller's active session ID, or ``None``.
    target_session_id: Resolved destination session ID, or ``None``.
    project_id: The project scope, or ``None``.
    tenant_id: The tenant scope, or empty string.
    allowlist: Target agent's allowlist, present only when ``code`` is
        :attr:`SendDeniedCode.TARGET_NOT_ALLOWED`. ``None`` for all other codes.
    """

    ok: bool
    code: SendDeniedCode | str
    message: str
    from_agent_ref: str
    to_agent_ref: str
    resolved_from_agent_id: str | None
    resolved_to_agent_id: str | None
    sender_session_id: str | None
    target_session_id: str | None
    project_id: str | None
    tenant_id: str
    allowlist: list[str] | None

    def to_dict(self) -> dict[str, Any]:
        """Render the denial as a JSON-compatible dict for tool output."""
        return {
            "ok": False,
            "code": self.code.value if isinstance(self.code, SendDeniedCode) else str(self.code),
            "message": self.message,
            "from_agent_ref": self.from_agent_ref,
            "to_agent_ref": self.to_agent_ref,
            "resolved_from_agent_id": self.resolved_from_agent_id,
            "resolved_to_agent_id": self.resolved_to_agent_id,
            "sender_session_id": self.sender_session_id,
            "target_session_id": self.target_session_id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "allowlist": self.allowlist,
        }


def _build_denial(
    *,
    code: SendDeniedCode,
    message: str,
    from_agent_ref: str,
    to_agent_ref: str,
    sender_session_id: str | None,
    project_id: str | None,
    tenant_id: str,
    resolved_from_agent_id: str | None,
    resolved_to_agent_id: str | None,
    target_session_id: str | None,
    allowlist: list[str] | None = None,
) -> SendDenied:
    return SendDenied(
        ok=False,
        code=code,
        message=message,
        from_agent_ref=from_agent_ref,
        to_agent_ref=to_agent_ref,
        resolved_from_agent_id=resolved_from_agent_id,
        resolved_to_agent_id=resolved_to_agent_id,
        sender_session_id=sender_session_id,
        target_session_id=target_session_id,
        project_id=project_id,
        tenant_id=tenant_id,
        allowlist=allowlist,
    )


def denial_code_from_error(
    exc: ValueError,
    *,
    from_agent_ref: str,
    to_agent_ref: str,
    sender_session_id: str | None,
    project_id: str | None,
    tenant_id: str,
    resolved_from_agent_id: str | None,
    resolved_to_agent_id: str | None,
    target_session_id: str | None,
    allowlist: list[str] | None = None,
) -> SendDenied:
    """Map a send-path ValueError to a structured :class:`SendDenied`.

    This function is the single translation point between the orchestrator's
    internal error messages and the machine-readable denial contract.  Each
    :attr:`SendDeniedCode` value corresponds to exactly one validation branch
    in ``AgentOrchestrator.send_message`` and its helpers.

    Parameters
    ----------
    exc:
        The ``ValueError`` raised by the orchestrator.
    from_agent_ref:
        Raw sender agent reference passed to the tool.
    to_agent_ref:
        Raw target agent reference passed to the tool.
    sender_session_id:
        Callers' active session ID (from ``ToolContext.session_id``).
    project_id:
        Project scope used for the send attempt.
    tenant_id:
        Tenant scope used for the send attempt.
    resolved_from_agent_id:
        Sender agent ID after resolution, or ``None`` if sender resolution failed.
    resolved_to_agent_id:
        Target agent ID after resolution, or ``None`` if target resolution failed.
    target_session_id:
        Resolved destination session ID, or ``None``.
    allowlist:
        Target agent's configured allowlist. Included in the denial payload only
        for :attr:`SendDeniedCode.TARGET_NOT_ALLOWED`.

    Returns
    -------
    SendDenied
        A frozen, JSON-serializable denial payload.
    """
    msg: str = exc.args[0] if exc.args else ""

    for code, predicate, payload_allowlist in [
        (SendDeniedCode.SENDER_NOT_FOUND, lambda text: "Sender agent not found" in text, None),
        (SendDeniedCode.SENDER_DISABLED, lambda text: "Sender agent is disabled" in text, None),
        (
            SendDeniedCode.SENDER_A2A_DISABLED,
            lambda text: "Sender agent-to-agent messaging is disabled" in text,
            None,
        ),
        (SendDeniedCode.TARGET_NOT_FOUND, lambda text: "Target agent not found" in text, None),
        (SendDeniedCode.TARGET_DISABLED, lambda text: "Target agent is disabled" in text, None),
        (
            SendDeniedCode.TARGET_A2A_DISABLED,
            lambda text: "Target agent-to-agent messaging is disabled" in text,
            None,
        ),
        (
            SendDeniedCode.TARGET_NOT_ALLOWED,
            lambda text: "does not accept messages from sender" in text,
            allowlist,
        ),
        (
            SendDeniedCode.SENDER_SESSION_REQUIRED,
            lambda text: text == "sender_session_id is required for agent-to-agent messaging",
            None,
        ),
        (
            SendDeniedCode.SENDER_SESSION_MISMATCH,
            lambda text: "Sender session" in text and "does not belong to sender agent" in text,
            None,
        ),
        (
            SendDeniedCode.TARGET_SESSION_NOT_FOUND,
            lambda text: "Session" in text and "was not found in project" in text,
            None,
        ),
        (
            SendDeniedCode.PROJECT_ID_REQUIRED,
            lambda text: text == "project_id is required when session_id is provided"
            or text == "Either session_id or project_id must be provided",
            None,
        ),
        (
            SendDeniedCode.TARGET_SESSION_MISMATCH,
            lambda text: "Session" in text and "does not belong to target agent" in text,
            None,
        ),
        (
            SendDeniedCode.TARGET_ACTIVE_SESSION_MISSING,
            lambda text: "No active session found for agent" in text and "in project" in text,
            None,
        ),
    ]:
        if predicate(msg):
            return _build_denial(
                code=code,
                message=msg,
                from_agent_ref=from_agent_ref,
                to_agent_ref=to_agent_ref,
                sender_session_id=sender_session_id,
                project_id=project_id,
                tenant_id=tenant_id,
                resolved_from_agent_id=resolved_from_agent_id,
                resolved_to_agent_id=resolved_to_agent_id,
                target_session_id=target_session_id,
                allowlist=payload_allowlist,
            )

    # Fallback – should not be reached for valid orchestrator paths, but
    # treated as an internal error rather than a silent swallow.
    return _build_denial(
        code=SendDeniedCode.SENDER_NOT_FOUND,  # conservative fallback
        message=f"Unrecognized send denial: {msg!r}",
        from_agent_ref=from_agent_ref,
        to_agent_ref=to_agent_ref,
        sender_session_id=sender_session_id,
        project_id=project_id,
        tenant_id=tenant_id,
        resolved_from_agent_id=resolved_from_agent_id,
        resolved_to_agent_id=resolved_to_agent_id,
        target_session_id=target_session_id,
        allowlist=None,
    )
