"""Spawn mode enumeration for multi-agent child sessions."""

from enum import Enum


class SpawnMode(str, Enum):
    """Mode for spawning child agents.

    Attributes:
        RUN: One-shot -- child executes, announces result, session ends.
        SESSION: Persistent -- child session stays alive for follow-ups.
    """

    RUN = "run"
    SESSION = "session"

    def __str__(self) -> str:
        return self.value
