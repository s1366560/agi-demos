"""Graph-level orchestrator for multi-agent DAG execution.

Manages the full lifecycle of a graph run: starting, scheduling nodes
via pattern coordinators, handling node completion/failure, emitting
domain events, and persisting state through repositories.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.domain.events.agent_events import (
    GraphHandoffEvent,
    GraphNodeCompletedEvent,
    GraphNodeFailedEvent,
    GraphNodeSkippedEvent,
    GraphNodeStartedEvent,
    GraphRunCancelledEvent,
    GraphRunCompletedEvent,
    GraphRunFailedEvent,
    GraphRunStartedEvent,
)
from src.domain.model.agent.graph import (
    AgentGraph,
    GraphRun,
    NodeExecution,
)
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.repositories.graph_repository import (
    AgentGraphRepository,
    GraphRunRepository,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SpawnResult,
)
from src.infrastructure.agent.orchestration.patterns import (
    PatternCoordinator,
    SwarmCoordinator,
    get_coordinator_for_pattern,
)

logger = logging.getLogger(__name__)


class GraphOrchestrator:
    """Manages the lifecycle of graph-based multi-agent runs.

    Delegates agent spawning to AgentOrchestrator and scheduling
    decisions to PatternCoordinator instances. Persists graph run
    state via repositories and emits domain events for SSE streaming.
    """

    def __init__(
        self,
        agent_orchestrator: AgentOrchestrator,
        graph_repo: AgentGraphRepository,
        run_repo: GraphRunRepository,
    ) -> None:
        self._agent_orchestrator = agent_orchestrator
        self._graph_repo = graph_repo
        self._run_repo = run_repo

    async def start_run(
        self,
        graph_id: str,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        *,
        initial_context: dict[str, Any] | None = None,
        parent_session_id: str = "",
        parent_agent_id: str = "system",
    ) -> tuple[GraphRun, list[GraphRunStartedEvent | GraphNodeStartedEvent]]:
        graph = await self._graph_repo.find_by_id(graph_id)
        if graph is None:
            raise ValueError(f"Agent graph not found: {graph_id}")
        if not graph.is_active:
            raise ValueError(f"Agent graph is inactive: {graph_id}")

        errors = graph.validate_graph()
        if errors:
            raise ValueError(f"Invalid graph: {'; '.join(errors)}")

        run = GraphRun(
            id=str(uuid.uuid4()),
            graph_id=graph.id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            max_total_steps=graph.max_total_steps,
            shared_context=dict(initial_context) if initial_context else {},
        )

        coordinator = get_coordinator_for_pattern(graph.pattern)
        entry_node_ids = coordinator.get_next_node_ids(graph, run)
        if not entry_node_ids:
            raise ValueError("Graph has no entry nodes to start")

        run.mark_running(entry_node_ids)

        events: list[GraphRunStartedEvent | GraphNodeStartedEvent] = []
        events.append(
            GraphRunStartedEvent(
                graph_run_id=run.id,
                graph_id=graph.id,
                graph_name=graph.name,
                pattern=graph.pattern.value,
                entry_node_ids=entry_node_ids,
            )
        )

        for node_id in entry_node_ids:
            node = graph.get_node(node_id)
            if node is None:
                continue

            node_exec = NodeExecution(
                id=str(uuid.uuid4()),
                graph_run_id=run.id,
                node_id=node.node_id,
                input_context=dict(run.shared_context),
            )

            spawn_result = await self._spawn_node(
                graph=graph,
                run=run,
                node_exec=node_exec,
                parent_agent_id=parent_agent_id,
                parent_session_id=parent_session_id or conversation_id,
                project_id=project_id,
                conversation_id=conversation_id,
            )

            node_exec.mark_running(spawn_result.session.conversation_id)
            run.add_node_execution(node_exec)
            run.increment_step()

            events.append(
                GraphNodeStartedEvent(
                    graph_run_id=run.id,
                    node_id=node.node_id,
                    node_label=node.label,
                    agent_definition_id=node.agent_definition_id,
                    agent_session_id=spawn_result.session.conversation_id,
                )
            )

        _ = await self._run_repo.save(run)
        return run, events

    async def on_node_completed(
        self,
        graph_id: str,
        run_id: str,
        node_id: str,
        output_context: dict[str, Any] | None = None,
        *,
        parent_session_id: str = "",
        parent_agent_id: str = "system",
    ) -> tuple[GraphRun, list[Any]]:
        graph = await self._graph_repo.find_by_id(graph_id)
        if graph is None:
            raise ValueError(f"Agent graph not found: {graph_id}")

        run = await self._run_repo.find_by_id(run_id)
        if run is None:
            raise ValueError(f"Graph run not found: {run_id}")
        if run.is_terminal:
            return run, []

        node_exec = run.get_node_execution(node_id)
        if node_exec is None:
            raise ValueError(f"Node execution not found for node_id={node_id}")

        node = graph.get_node(node_id)
        node_label = node.label if node else node_id

        node_exec.mark_completed(output_context)
        if output_context:
            run.update_shared_context(output_context)

        events: list[Any] = []
        events.append(
            GraphNodeCompletedEvent(
                graph_run_id=run.id,
                node_id=node_id,
                node_label=node_label,
                output_keys=list(output_context.keys()) if output_context else [],
                duration_seconds=node_exec.duration_seconds,
            )
        )

        coordinator = get_coordinator_for_pattern(graph.pattern)

        if coordinator.should_complete_run(graph, run):
            run.mark_completed()
            events.append(
                GraphRunCompletedEvent(
                    graph_run_id=run.id,
                    graph_id=graph.id,
                    graph_name=graph.name,
                    total_steps=run.total_steps,
                    duration_seconds=run.duration_seconds,
                )
            )
        else:
            next_node_ids = coordinator.get_next_node_ids(graph, run)
            for nid in next_node_ids:
                node_events = await self._schedule_node(
                    graph=graph,
                    run=run,
                    node_id=nid,
                    _coordinator=coordinator,
                    parent_agent_id=parent_agent_id,
                    parent_session_id=parent_session_id or run.conversation_id,
                )
                events.extend(node_events)

        _ = await self._run_repo.save(run)
        return run, events

    async def on_node_failed(
        self,
        graph_id: str,
        run_id: str,
        node_id: str,
        error_message: str,
    ) -> tuple[GraphRun, list[Any]]:
        graph = await self._graph_repo.find_by_id(graph_id)
        if graph is None:
            raise ValueError(f"Agent graph not found: {graph_id}")

        run = await self._run_repo.find_by_id(run_id)
        if run is None:
            raise ValueError(f"Graph run not found: {run_id}")
        if run.is_terminal:
            return run, []

        node_exec = run.get_node_execution(node_id)
        if node_exec is None:
            raise ValueError(f"Node execution not found for node_id={node_id}")

        node = graph.get_node(node_id)
        node_label = node.label if node else node_id

        node_exec.mark_failed(error_message)

        events: list[Any] = []
        events.append(
            GraphNodeFailedEvent(
                graph_run_id=run.id,
                node_id=node_id,
                node_label=node_label,
                error_message=error_message,
            )
        )

        run.mark_failed(f"Node '{node_label}' failed: {error_message}")
        events.append(
            GraphRunFailedEvent(
                graph_run_id=run.id,
                graph_id=graph.id,
                graph_name=graph.name,
                error_message=error_message,
                failed_node_id=node_id,
            )
        )

        _ = await self._run_repo.save(run)
        return run, events

    async def cancel_run(
        self,
        run_id: str,
        *,
        reason: str = "",
    ) -> tuple[GraphRun, list[GraphRunCancelledEvent]]:
        run = await self._run_repo.find_by_id(run_id)
        if run is None:
            raise ValueError(f"Graph run not found: {run_id}")
        if run.is_terminal:
            return run, []

        graph = await self._graph_repo.find_by_id(run.graph_id)
        graph_name = graph.name if graph else ""

        run.mark_cancelled()

        events = [
            GraphRunCancelledEvent(
                graph_run_id=run.id,
                graph_id=run.graph_id,
                graph_name=graph_name,
                reason=reason,
            )
        ]

        _ = await self._run_repo.save(run)
        return run, events

    async def handoff_node(
        self,
        graph_id: str,
        run_id: str,
        from_node_id: str,
        to_node_id: str,
        *,
        context_summary: str = "",
        parent_session_id: str = "",
        parent_agent_id: str = "system",
    ) -> tuple[GraphRun, list[Any]]:
        graph = await self._graph_repo.find_by_id(graph_id)
        if graph is None:
            raise ValueError(f"Agent graph not found: {graph_id}")

        run = await self._run_repo.find_by_id(run_id)
        if run is None:
            raise ValueError(f"Graph run not found: {run_id}")
        if run.is_terminal:
            return run, []

        coordinator = get_coordinator_for_pattern(graph.pattern)
        if not isinstance(coordinator, SwarmCoordinator):
            raise ValueError(
                f"Handoff is only supported in SWARM pattern, got {graph.pattern.value}"
            )

        validation_error = coordinator.validate_handoff_target(graph, run, to_node_id)
        if validation_error:
            raise ValueError(validation_error)

        from_node = graph.get_node(from_node_id)
        to_node = graph.get_node(to_node_id)

        events: list[Any] = []
        events.append(
            GraphHandoffEvent(
                graph_run_id=run.id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                from_label=from_node.label if from_node else "",
                to_label=to_node.label if to_node else "",
                context_summary=context_summary,
            )
        )

        node_events = await self._schedule_node(
            graph=graph,
            run=run,
            node_id=to_node_id,
            _coordinator=coordinator,
            parent_agent_id=parent_agent_id,
            parent_session_id=parent_session_id or run.conversation_id,
        )
        events.extend(node_events)

        _ = await self._run_repo.save(run)
        return run, events

    async def get_run_status(self, run_id: str) -> GraphRun | None:
        return await self._run_repo.find_by_id(run_id)

    async def list_runs_for_graph(self, graph_id: str) -> list[GraphRun]:
        return await self._run_repo.list_by_graph(graph_id)

    async def _schedule_node(
        self,
        graph: AgentGraph,
        run: GraphRun,
        node_id: str,
        _coordinator: PatternCoordinator,
        parent_agent_id: str,
        parent_session_id: str,
    ) -> list[GraphNodeStartedEvent | GraphNodeSkippedEvent]:
        node = graph.get_node(node_id)
        if node is None:
            logger.warning("Skipping unknown node_id=%s in graph=%s", node_id, graph.id)
            return []

        node_exec = NodeExecution(
            id=str(uuid.uuid4()),
            graph_run_id=run.id,
            node_id=node.node_id,
            input_context=dict(run.shared_context),
        )

        try:
            spawn_result = await self._spawn_node(
                graph=graph,
                run=run,
                node_exec=node_exec,
                parent_agent_id=parent_agent_id,
                parent_session_id=parent_session_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
            )
        except Exception:
            logger.exception("Failed to spawn agent for node=%s in run=%s", node_id, run.id)
            node_exec.mark_skipped()
            run.add_node_execution(node_exec)
            return [
                GraphNodeSkippedEvent(
                    graph_run_id=run.id,
                    node_id=node.node_id,
                    node_label=node.label,
                    reason="Failed to spawn agent",
                )
            ]

        node_exec.mark_running(spawn_result.session.conversation_id)
        run.add_node_execution(node_exec)
        run.increment_step()

        return [
            GraphNodeStartedEvent(
                graph_run_id=run.id,
                node_id=node.node_id,
                node_label=node.label,
                agent_definition_id=node.agent_definition_id,
                agent_session_id=spawn_result.session.conversation_id,
            )
        ]

    async def _spawn_node(
        self,
        graph: AgentGraph,
        run: GraphRun,
        node_exec: NodeExecution,
        parent_agent_id: str,
        parent_session_id: str,
        project_id: str,
        conversation_id: str,
    ) -> SpawnResult:
        node = graph.get_node(node_exec.node_id)
        if node is None:
            raise ValueError(f"Node not found: {node_exec.node_id}")

        instruction_parts = [node.instruction] if node.instruction else []
        if node_exec.input_context:
            context_str = ", ".join(f"{k}={v}" for k, v in node_exec.input_context.items())
            instruction_parts.append(f"Context: {context_str}")

        message = "\n".join(instruction_parts) if instruction_parts else node.label

        metadata: dict[str, Any] = {
            "graph_run_id": run.id,
            "graph_id": graph.id,
            "node_id": node.node_id,
            "node_label": node.label,
            "graph_pattern": graph.pattern.value,
        }
        if node.config:
            metadata["node_config"] = node.config

        return await self._agent_orchestrator.spawn_agent(
            parent_agent_id=parent_agent_id,
            target_agent_id=node.agent_definition_id,
            message=message,
            mode=SpawnMode.RUN,
            parent_session_id=parent_session_id,
            project_id=project_id,
            conversation_id=conversation_id,
            metadata=metadata,
        )
