"""Reflector port — agent-tool-call boundary for the reflection loop.

The concrete implementation is expected to be an LLM-backed agent that
returns *structured* ``ReflectionVerdict`` values (NOT free text). This port
exists so the application service can stay framework-agnostic and so tests
can stub the agent without spinning up an LLM.

Per the project's Agent-First rule: subjective verdicts (create / reinforce /
deprecate) MUST come from this port. Heuristic shortcuts in the service layer
are forbidden.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.flow.friction_signal import FrictionSignal
from src.domain.model.flow.playbook import Playbook
from src.domain.model.flow.reflection_verdict import ReflectionVerdict


class ReflectorPort(ABC):
    """Adapter to the reflector agent / LLM tool-call."""

    @abstractmethod
    async def reflect(
        self,
        *,
        project_id: str,
        signals: list[FrictionSignal],
        existing_playbooks: list[Playbook],
    ) -> list[ReflectionVerdict]:
        """Given a window of friction signals + current playbooks, return
        zero or more verdicts describing what to do next.

        Implementations MUST emit one verdict per recommended change; do not
        bundle multiple actions into one verdict.
        """
