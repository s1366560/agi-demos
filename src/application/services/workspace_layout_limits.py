"""Shared guardrails for workspace arrangement geometry."""

from __future__ import annotations

import math

MAX_WORKSPACE_HEX_COORDINATE = 24
MAX_WORKSPACE_POSITION = 1000.0


def validate_hex_coordinate(value: int, *, field_name: str) -> None:
    """Reject geometry outside the supported workspace radius."""
    if abs(value) > MAX_WORKSPACE_HEX_COORDINATE:
        raise ValueError(
            f"{field_name} must be between "
            f"{-MAX_WORKSPACE_HEX_COORDINATE} and {MAX_WORKSPACE_HEX_COORDINATE}"
        )


def validate_hex_target(hex_q: int, hex_r: int) -> None:
    """Reject placements outside the supported hex radius."""
    validate_hex_coordinate(hex_q, field_name="hex_q")
    validate_hex_coordinate(hex_r, field_name="hex_r")
    hex_s = -hex_q - hex_r
    distance = max(abs(hex_q), abs(hex_r), abs(hex_s))
    if distance > MAX_WORKSPACE_HEX_COORDINATE:
        raise ValueError(
            f"Hex target must stay within workspace radius {MAX_WORKSPACE_HEX_COORDINATE}"
        )


def validate_position_value(value: float, *, field_name: str) -> None:
    """Reject non-finite or extreme coordinates that can break the board."""
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    if abs(value) > MAX_WORKSPACE_POSITION:
        raise ValueError(
            f"{field_name} must be between {-MAX_WORKSPACE_POSITION} and {MAX_WORKSPACE_POSITION}"
        )
