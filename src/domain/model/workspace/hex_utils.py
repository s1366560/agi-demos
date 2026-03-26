"""Axial hex-coordinate math for flat-top orientation: (q, r), s = -q - r."""

from __future__ import annotations

import math

ADJACENT_OFFSETS: frozenset[tuple[int, int]] = frozenset(
    [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]
)

_SQRT3 = math.sqrt(3)


def is_adjacent(q1: int, r1: int, q2: int, r2: int) -> bool:
    return (q2 - q1, r2 - r1) in ADJACENT_OFFSETS


def hex_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    """Cube-coordinate manhattan distance (shortest hex path length)."""
    dq = q2 - q1
    dr = r2 - r1
    ds = -(dq + dr)
    return max(abs(dq), abs(dr), abs(ds))


def hex_neighbors(q: int, r: int) -> list[tuple[int, int]]:
    return [(q + dq, r + dr) for dq, dr in ADJACENT_OFFSETS]


def hex_to_pixel(q: int, r: int, size: float = 40.0) -> tuple[float, float]:
    """Flat-top: axial (q, r) -> pixel (x, y). Size = center-to-vertex radius."""
    x = size * (3.0 / 2.0 * q)
    y = size * (_SQRT3 / 2.0 * q + _SQRT3 * r)
    return (x, y)


def pixel_to_hex(x: float, y: float, size: float = 40.0) -> tuple[int, int]:
    """Flat-top: pixel (x, y) -> nearest axial hex via cube rounding."""
    q_frac = (2.0 / 3.0 * x) / size
    r_frac = (-1.0 / 3.0 * x + _SQRT3 / 3.0 * y) / size
    return _axial_round(q_frac, r_frac)


def ordered_pair(q1: int, r1: int, q2: int, r2: int) -> tuple[int, int, int, int]:
    """Canonical ordering of a hex pair to prevent duplicate connections."""
    if (q1, r1) > (q2, r2):
        return (q2, r2, q1, r1)
    return (q1, r1, q2, r2)


def _axial_round(q_frac: float, r_frac: float) -> tuple[int, int]:
    """Round fractional axial coords to nearest hex (cube-coordinate rounding)."""
    s_frac = -q_frac - r_frac

    q_round = round(q_frac)
    r_round = round(r_frac)
    s_round = round(s_frac)

    q_diff = abs(q_round - q_frac)
    r_diff = abs(r_round - r_frac)
    s_diff = abs(s_round - s_frac)

    if q_diff > r_diff and q_diff > s_diff:
        q_round = -r_round - s_round
    elif r_diff > s_diff:
        r_round = -q_round - s_round

    return (q_round, r_round)
