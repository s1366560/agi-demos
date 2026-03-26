from __future__ import annotations

import math

import pytest

from src.domain.model.workspace.hex_utils import (
    ADJACENT_OFFSETS,
    _axial_round,  # pyright: ignore[reportPrivateUsage]
    hex_distance,
    hex_neighbors,
    hex_to_pixel,
    is_adjacent,
    ordered_pair,
    pixel_to_hex,
)

_SQRT3 = math.sqrt(3)


@pytest.mark.unit
class TestAdjacentOffsets:
    def test_count(self) -> None:
        assert len(ADJACENT_OFFSETS) == 6

    def test_is_frozenset(self) -> None:
        assert isinstance(ADJACENT_OFFSETS, frozenset)

    def test_contains_all_six_directions(self) -> None:
        expected = {(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)}
        assert expected == ADJACENT_OFFSETS


@pytest.mark.unit
class TestIsAdjacent:
    @pytest.mark.parametrize(
        "q1,r1,q2,r2",
        [
            (0, 0, 1, 0),
            (0, 0, -1, 0),
            (0, 0, 0, 1),
            (0, 0, 0, -1),
            (0, 0, 1, -1),
            (0, 0, -1, 1),
        ],
    )
    def test_all_six_neighbors_of_origin(self, q1: int, r1: int, q2: int, r2: int) -> None:
        assert is_adjacent(q1, r1, q2, r2) is True

    def test_same_hex_not_adjacent(self) -> None:
        assert is_adjacent(0, 0, 0, 0) is False

    def test_two_steps_away_not_adjacent(self) -> None:
        assert is_adjacent(0, 0, 2, 0) is False

    def test_non_origin_adjacent(self) -> None:
        assert is_adjacent(3, -2, 4, -2) is True
        assert is_adjacent(3, -2, 3, -1) is True

    def test_non_origin_not_adjacent(self) -> None:
        assert is_adjacent(3, -2, 5, -2) is False


@pytest.mark.unit
class TestHexDistance:
    def test_same_hex(self) -> None:
        assert hex_distance(0, 0, 0, 0) == 0

    def test_adjacent_distance_one(self) -> None:
        for dq, dr in ADJACENT_OFFSETS:
            assert hex_distance(0, 0, dq, dr) == 1

    def test_two_steps(self) -> None:
        assert hex_distance(0, 0, 2, 0) == 2

    def test_diagonal_path(self) -> None:
        assert hex_distance(0, 0, 2, -2) == 2

    def test_symmetric(self) -> None:
        assert hex_distance(1, 2, 4, -1) == hex_distance(4, -1, 1, 2)

    def test_non_origin(self) -> None:
        assert hex_distance(3, -2, 5, -4) == 2


@pytest.mark.unit
class TestHexNeighbors:
    def test_origin_neighbors(self) -> None:
        result = hex_neighbors(0, 0)
        assert len(result) == 6
        assert set(result) == {(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)}

    def test_non_origin_neighbors(self) -> None:
        result = hex_neighbors(2, -1)
        assert len(result) == 6
        expected = {(3, -1), (1, -1), (2, 0), (2, -2), (3, -2), (1, 0)}
        assert set(result) == expected

    def test_all_neighbors_are_adjacent(self) -> None:
        for nq, nr in hex_neighbors(5, 3):
            assert is_adjacent(5, 3, nq, nr)


@pytest.mark.unit
class TestHexToPixel:
    def test_origin(self) -> None:
        x, y = hex_to_pixel(0, 0)
        assert x == pytest.approx(0.0)
        assert y == pytest.approx(0.0)

    def test_unit_q(self) -> None:
        x, y = hex_to_pixel(1, 0, size=40.0)
        assert x == pytest.approx(60.0)
        assert y == pytest.approx(_SQRT3 * 20.0)

    def test_unit_r(self) -> None:
        x, y = hex_to_pixel(0, 1, size=40.0)
        assert x == pytest.approx(0.0)
        assert y == pytest.approx(_SQRT3 * 40.0)

    def test_custom_size(self) -> None:
        x, y = hex_to_pixel(1, 0, size=100.0)
        assert x == pytest.approx(150.0)
        assert y == pytest.approx(_SQRT3 * 50.0)


@pytest.mark.unit
class TestPixelToHex:
    def test_origin(self) -> None:
        q, r = pixel_to_hex(0.0, 0.0)
        assert (q, r) == (0, 0)

    def test_roundtrip_integer_hex(self) -> None:
        for q in range(-3, 4):
            for r in range(-3, 4):
                px, py = hex_to_pixel(q, r, size=40.0)
                rq, rr = pixel_to_hex(px, py, size=40.0)
                assert (rq, rr) == (q, r), f"Roundtrip failed for ({q}, {r})"

    def test_roundtrip_custom_size(self) -> None:
        size = 80.0
        for q in range(-2, 3):
            for r in range(-2, 3):
                px, py = hex_to_pixel(q, r, size=size)
                rq, rr = pixel_to_hex(px, py, size=size)
                assert (rq, rr) == (q, r)

    def test_near_boundary_snaps_correctly(self) -> None:
        px, py = hex_to_pixel(1, 0, size=40.0)
        rq, rr = pixel_to_hex(px + 0.1, py - 0.1, size=40.0)
        assert (rq, rr) == (1, 0)


@pytest.mark.unit
class TestOrderedPair:
    def test_already_ordered(self) -> None:
        assert ordered_pair(0, 0, 1, 0) == (0, 0, 1, 0)

    def test_reversed_input(self) -> None:
        assert ordered_pair(1, 0, 0, 0) == (0, 0, 1, 0)

    def test_same_hex(self) -> None:
        assert ordered_pair(2, 3, 2, 3) == (2, 3, 2, 3)

    def test_symmetry(self) -> None:
        assert ordered_pair(3, -1, 1, 2) == ordered_pair(1, 2, 3, -1)

    def test_negative_coords(self) -> None:
        assert ordered_pair(-1, 2, -2, 3) == (-2, 3, -1, 2)


@pytest.mark.unit
class TestAxialRound:
    def test_exact_integer(self) -> None:
        assert _axial_round(2.0, 3.0) == (2, 3)

    def test_slight_fractional(self) -> None:
        assert _axial_round(2.1, 2.9) == (2, 3)

    def test_cube_constraint_preserved(self) -> None:
        q, r = _axial_round(0.4, 0.3)
        s = -q - r
        assert q + r + s == 0

    def test_negative_coords(self) -> None:
        q, r = _axial_round(-1.2, 0.8)
        s = -q - r
        assert q + r + s == 0
