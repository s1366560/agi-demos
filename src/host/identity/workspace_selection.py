"""Resolve explicit workspace context before requesting a judgment among eligible projects."""

from collections.abc import Awaitable, Callable
from datetime import datetime

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextCandidate,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
)
from src.domain.ports.repositories.workspace_context_repository import WorkspaceContextRepository

type ChooseContext = Callable[
    [str, tuple[WorkspaceContextCandidate, ...]], Awaitable[WorkspaceContextCandidate]
]


async def get_or_initialize(
    repository: WorkspaceContextRepository,
    user_id: str,
    observed_at: datetime,
    choose: ChooseContext | None = None,
) -> WorkspaceContextAccess:
    current = await repository.get_accessible(user_id)
    if current is not None:
        return current
    candidates = await repository.list_candidates(user_id)
    if len(candidates) == 1:
        selected = candidates[0]
    elif candidates and choose is not None:
        selected = await choose(user_id, candidates)
    else:
        raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE)
    return await repository.initialize(user_id, candidate=selected, observed_at=observed_at)
