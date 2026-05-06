"""Tests for delivery readiness classification (P4-Ready)."""

from __future__ import annotations

import pytest

from src.domain.model.delivery.readiness import (
    DeliveryReadiness,
    DeliveryStatus,
    classify_delivery_readiness,
)


@pytest.mark.unit
class TestDeliveryReadiness:
    def test_none_status_is_unknown(self) -> None:
        report = classify_delivery_readiness(None)
        assert report.readiness is DeliveryReadiness.UNKNOWN

    def test_modified_files_is_dirty(self) -> None:
        status = DeliveryStatus(branch="feat/x", modified_files=("src/foo.py",))
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.DIRTY
        assert "modified" in report.reason

    def test_untracked_files_is_dirty(self) -> None:
        status = DeliveryStatus(branch="feat/x", untracked_files=("note.txt",))
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.DIRTY

    def test_behind_base_is_stale(self) -> None:
        status = DeliveryStatus(
            branch="feat/x", behind=2, ahead=1, commits_since_base=1
        )
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.STALE
        assert "behind" in report.reason

    def test_clean_with_no_commits_is_empty(self) -> None:
        status = DeliveryStatus(branch="feat/x", ahead=0, commits_since_base=0)
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.EMPTY

    def test_clean_with_ahead_is_ready(self) -> None:
        status = DeliveryStatus(branch="feat/x", ahead=3, commits_since_base=3)
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.READY
        assert report.is_ready is True

    def test_dirty_takes_precedence_over_stale(self) -> None:
        status = DeliveryStatus(
            branch="feat/x",
            behind=5,
            ahead=2,
            modified_files=("src/foo.py",),
            commits_since_base=2,
        )
        report = classify_delivery_readiness(status)
        assert report.readiness is DeliveryReadiness.DIRTY
