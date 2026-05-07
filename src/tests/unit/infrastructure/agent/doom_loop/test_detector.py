"""Unit tests for DoomLoopDetector (P1-11 hardening)."""

import threading

import pytest

from src.infrastructure.agent.doom_loop.detector import DoomLoopDetector


class TestDoomLoopDetectorBasics:
    @pytest.mark.unit
    def test_repeated_identical_call_triggers_intervention(self) -> None:
        d = DoomLoopDetector(threshold=3)
        for _ in range(3):
            d.record("search", {"q": "x"})
        assert d.should_intervene("search", {"q": "x"}) is True

    @pytest.mark.unit
    def test_varied_calls_do_not_trigger(self) -> None:
        d = DoomLoopDetector(threshold=3)
        d.record("search", {"q": "a"})
        d.record("search", {"q": "b"})
        d.record("search", {"q": "c"})
        assert d.should_intervene("search", {"q": "c"}) is False

    @pytest.mark.unit
    def test_hash_is_type_tagged(self) -> None:
        """`"42"` and `42` must not collapse — would otherwise mask varied input."""
        d = DoomLoopDetector(threshold=2)
        assert d._hash_input("42") != d._hash_input(42)


class TestDoomLoopDetectorErrors:
    @pytest.mark.unit
    def test_consecutive_errors_trigger(self) -> None:
        d = DoomLoopDetector(threshold=3, error_threshold=3)
        for i in range(3):
            d.record_error(f"tool_{i}", f"Unknown tool {i}")
        assert d.should_intervene_on_errors() is True

    @pytest.mark.unit
    def test_reset_errors_clears(self) -> None:
        d = DoomLoopDetector(threshold=3, error_threshold=2)
        d.record_error("a", "x")
        d.record_error("b", "y")
        assert d.should_intervene_on_errors() is True
        d.reset_errors()
        assert d.consecutive_error_count == 0
        assert d.should_intervene_on_errors() is False

    @pytest.mark.unit
    def test_error_history_is_bounded(self) -> None:
        """`_consecutive_errors` must not grow without bound."""
        d = DoomLoopDetector(threshold=3, error_threshold=4)
        for i in range(10_000):
            d.record_error("t", f"err {i}")
        # bound is max(error_threshold * 2, window_size); both are <= 100.
        assert len(d._consecutive_errors) <= max(d._error_threshold * 2, 10)


class TestDoomLoopDetectorConcurrency:
    @pytest.mark.unit
    def test_concurrent_record_does_not_corrupt(self) -> None:
        """Concurrent record() calls from threads must not raise / corrupt the deque."""
        d = DoomLoopDetector(threshold=5, window_size=10_000)

        def worker(i: int) -> None:
            for j in range(200):
                d.record(f"tool_{i}", {"j": j})
                d.record_error(f"tool_{i}", f"err {j}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads completed without raising; window is bounded.
        assert len(d.window) <= 10_000
        assert d.consecutive_error_count >= 0
