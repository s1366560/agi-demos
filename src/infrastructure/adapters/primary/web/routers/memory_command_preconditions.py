"""Keep explicit versioned HTTP commands out of the legacy mutation path."""

from fastapi import HTTPException

from src.infrastructure.i18n import gettext as _


def require_memory_command_availability(
    *, enabled: bool, change_id: str | None, expected_revision: str | None
) -> None:
    """Absent command headers retain compatibility; supplied headers are binding."""
    if not enabled and (change_id is not None or expected_revision is not None):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "memory_command_unavailable",
                "message": _("Versioned memory commands are unavailable for this project"),
            },
        )
