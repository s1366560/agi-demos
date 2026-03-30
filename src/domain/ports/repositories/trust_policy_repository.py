from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.trust.trust_policy import TrustPolicy


class TrustPolicyRepository(ABC):
    """Repository interface for trust policy persistence."""

    @abstractmethod
    async def save(self, policy: TrustPolicy) -> TrustPolicy: ...

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        *,
        agent_instance_id: str | None = None,
    ) -> list[TrustPolicy]: ...

    @abstractmethod
    async def check_always_trust(
        self,
        workspace_id: str,
        agent_instance_id: str,
        action_type: str,
    ) -> bool: ...
