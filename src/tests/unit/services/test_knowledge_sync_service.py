"""KnowledgeSyncService forwards explicit resolutions without rewriting them."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from src.application.services.knowledge_sync_service import KnowledgeSyncService
from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncContent,
)

pytestmark = pytest.mark.unit

SCOPE = KnowledgeSyncScope(tenant_id="tenant", project_id="project", actor_id="actor")


@dataclass
class StubRepository:
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: KnowledgeSyncResolution
    ) -> KnowledgeSyncOutcome:
        self.calls.append(("resolve", scope, change_id, resolution))
        return KnowledgeSyncOutcome(
            receipt_json=json.dumps({"status": "resolved", "decision": resolution.decision})
        )


def resolution(decision: str = "keep_both", **kwargs: Any) -> KnowledgeSyncResolution:
    return KnowledgeSyncResolution(
        conflict_id=str(uuid4()), expected_current_revision=2, decision=decision, **kwargs
    )


async def test_resolve_forwards_keep_both_verbatim() -> None:
    repository = StubRepository()
    service = KnowledgeSyncService(repository=repository)
    change_id = str(uuid4())
    outcome = await service.resolve(SCOPE, change_id, resolution())
    assert len(repository.calls) == 1
    operation, scope, forwarded_change_id, forwarded = repository.calls[0]
    assert operation == "resolve" and scope is SCOPE and forwarded_change_id == change_id
    assert forwarded.decision == "keep_both" and forwarded.expected_current_revision == 2
    assert outcome.to_dict()["receipt"] == {"status": "resolved", "decision": "keep_both"}
    assert not outcome.replayed


async def test_resolve_requires_canonical_change_id() -> None:
    service = KnowledgeSyncService(repository=StubRepository())
    with pytest.raises(KnowledgeSyncError, match="change_id_invalid"):
        await service.resolve(SCOPE, "not-a-uuid", resolution())


def test_keep_both_resolution_rejects_content_and_unknown_decision() -> None:
    with pytest.raises(KnowledgeSyncError, match="input_invalid"):
        resolution(content=MemorySyncContent(title="t", content="c"))
    with pytest.raises(KnowledgeSyncError, match="input_invalid"):
        resolution(decision="discard")
