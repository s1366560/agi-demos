"""Atomically enforce structural spawn budgets and persist a running child."""

from src.domain.model.agent.subagent_run import SubAgentRun

from .async_run_registry_v2 import registry_transaction_v2
from .owner_lease_v2 import OWNER_PROTOCOL_V2
from .run_registry import SubAgentRunRegistry


async def reserve_session_run_v2(
    registry: SubAgentRunRegistry,
    *,
    max_active_runs: int,
    max_children_per_requester: int,
    max_active_runs_per_lineage: int,
    conversation_id: str,
    subagent_name: str,
    task: str,
    metadata: dict[str, object],
    requester_session_key: str | None = None,
    parent_run_id: str | None = None,
    lineage_root_run_id: str | None = None,
) -> SubAgentRun | str:
    """Commit the reservation before any callback or started event is emitted."""

    def reserve(memory: SubAgentRunRegistry) -> SubAgentRun | str:
        active = memory.count_active_runs(conversation_id)
        if active >= max_active_runs:
            return f"Error: active SubAgent sessions limit reached ({active}/{max_active_runs})"
        requester = memory.count_active_runs_for_requester(
            conversation_id, requester_session_key or ""
        )
        if requester >= max_children_per_requester:
            return (
                "Error: requester SubAgent sessions limit reached "
                f"({requester}/{max_children_per_requester})"
            )
        lineage = lineage_root_run_id
        if lineage:
            active_lineage = memory.count_active_runs_for_lineage(conversation_id, lineage)
            if active_lineage >= max_active_runs_per_lineage:
                return (
                    "Error: lineage SubAgent sessions limit reached "
                    f"({active_lineage}/{max_active_runs_per_lineage})"
                )
        run = memory.create_run(
            conversation_id=conversation_id,
            subagent_name=subagent_name,
            task=task,
            metadata={**metadata, "execution_protocol": OWNER_PROTOCOL_V2},
            requester_session_key=requester_session_key,
            parent_run_id=parent_run_id,
            lineage_root_run_id=lineage_root_run_id,
        )
        running = memory.mark_running(conversation_id, run.run_id)
        assert running is not None
        return running

    return await registry_transaction_v2(registry, reserve, write=True)
