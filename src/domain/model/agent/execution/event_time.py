"""Event time generator for monotonic event ordering.

Generates (event_time_us, event_counter) composite keys for event ordering.
event_time_us is a microsecond-precision UTC timestamp, and event_counter
is a monotonically increasing counter within the same microsecond.
"""

from datetime import datetime, timezone


class EventTimeGenerator:
    """Generate monotonic (event_time_us, event_counter) composite sort keys.

    Ensures strict ordering even when multiple events occur within the same
    microsecond or when system clock drifts backward.

    Attributes:
        _last_time_us: Last generated microsecond timestamp.
        _counter: Counter within the current microsecond.
    """

    def __init__(
        self,
        last_time_us: int = 0,
        last_counter: int = 0,
    ) -> None:
        self._last_time_us = last_time_us
        self._counter = last_counter

    def next(self) -> tuple[int, int]:
        """Generate the next (event_time_us, event_counter) pair.

        Returns:
            Tuple of (event_time_us, event_counter) guaranteed to be
            monotonically increasing relative to previous calls.
        """
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

        if now_us <= self._last_time_us:
            # Same microsecond or clock drift backward: increment counter
            self._counter += 1
        else:
            self._last_time_us = now_us
            self._counter = 0

        return (self._last_time_us, self._counter)

    @property
    def last_time_us(self) -> int:
        return self._last_time_us

    @property
    def last_counter(self) -> int:
        return self._counter
