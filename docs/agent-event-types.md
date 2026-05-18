# Agent Event Types

`src/domain/events/types.py` is the single source of truth for agent event names.

Last checked against code: 2026-05-18.

## Summary

- Current `AgentEventType` values: **163**.
- Internal events: `compact_needed`, `retry`.
- Delta events not persisted by default: `thought_delta`, `text_delta`, `text_start`,
  `text_end`, `act_delta`.
- Terminal events: `complete`, `error`, `cancelled`.
- HITL request events: `clarification_asked`, `decision_asked`, `env_var_requested`,
  `permission_asked`, `elicitation_asked`, `a2ui_action_asked`.

## Event Pipeline

```text
Agent runtime / tools
  -> AgentDomainEvent subclasses
  -> to_event_dict() / event converter
  -> Redis stream and PostgreSQL event persistence
  -> WebSocket delivery
  -> web/src/services/agentService.ts
  -> web/src/services/agent/messageRouter.ts
  -> web/src/utils/sseEventAdapter.ts
  -> Zustand stores and timeline UI
```

## Core Categories

| Category | Event values |
|---|---|
| Status | `status`, `start`, `complete`, `error`, `cancelled` |
| Thinking/text | `thought`, `thought_delta`, `text_start`, `text_delta`, `text_end` |
| Tool execution | `act`, `act_delta`, `observe`, `tool_policy_denied`, `tools_updated` |
| Messages | `message`, `user_message`, `assistant_message` |
| HITL | `clarification_asked`, `clarification_answered`, `decision_asked`, `decision_answered`, `env_var_requested`, `env_var_provided`, `permission_asked`, `permission_replied`, `elicitation_asked`, `elicitation_answered`, `a2ui_action_asked`, `a2ui_action_answered` |
| Context/memory | `compact_needed`, `context_compressed`, `context_status`, `context_summary_generated`, `context_compacted`, `memory_recalled`, `memory_captured` |
| Skills/patterns | `pattern_match`, `skill_matched`, `skill_execution_start`, `skill_execution_complete`, `skill_fallback` |
| Sandbox | `sandbox_created`, `sandbox_terminated`, `sandbox_status`, `desktop_started`, `desktop_stopped`, `desktop_status`, `terminal_started`, `terminal_stopped`, `terminal_status`, `http_service_started`, `http_service_updated`, `http_service_stopped`, `http_service_error` |
| Artifacts/canvas/MCP apps | `artifact_created`, `artifact_ready`, `artifact_error`, `artifacts_batch`, `artifact_open`, `artifact_update`, `artifact_close`, `canvas_updated`, `mcp_app_result`, `mcp_app_registered` |
| Subagents | `subagent_routed`, `subagent_started`, `subagent_completed`, `subagent_failed`, `subagent_spawning`, `subagent_doom_loop`, `subagent_retry`, `subagent_queued`, `subagent_killed`, `subagent_steered`, `subagent_depth_limited`, `subagent_session_update`, `subagent_spawn_rejected`, `subagent_announce_retry`, `subagent_orphan_detected`, `subagent_announce_sent`, `subagent_announce_received`, `subagent_announce_expired`, `subagent_delegation` |
| Agent orchestration | `plan_suggested`, `selection_trace`, `policy_filtered`, `parallel_started`, `parallel_completed`, `background_launched`, `agent_spawned`, `agent_completed`, `agent_message_sent`, `agent_message_received`, `agent_stopped` |
| Graph orchestration | `graph_run_started`, `graph_run_completed`, `graph_run_failed`, `graph_run_cancelled`, `graph_node_started`, `graph_node_completed`, `graph_node_failed`, `graph_node_skipped`, `graph_handoff` |
| Workspace | `workspace_member_joined`, `workspace_member_left`, `workspace_updated`, `workspace_deleted`, `workspace_agent_bound`, `workspace_agent_unbound`, `workspace_message_created`, `topology_updated` |
| Blackboard | `blackboard_post_created`, `blackboard_post_updated`, `blackboard_post_deleted`, `blackboard_reply_created`, `blackboard_reply_updated`, `blackboard_reply_deleted`, `blackboard_file_created`, `blackboard_file_updated`, `blackboard_file_deleted`, `blackboard_directory_deleted` |
| Workspace tasks/plans | `workspace_task_assigned`, `workspace_task_created`, `workspace_task_updated`, `workspace_task_deleted`, `workspace_task_status_changed`, `workspace_plan_updated`, `workspace_goal_materialized`, `workspace_decomposition_complete`, `workspace_worker_dispatched`, `workspace_worker_report_submitted`, `workspace_adjudication_complete`, `workspace_goal_completed` |
| Task execution/recovery | `task_list_updated`, `task_updated`, `task_start`, `task_complete`, `task_execution_session_updated`, `task_execution_incident_opened`, `task_recovery_action_started`, `task_recovery_action_completed` |
| Structured agent actions | `agent_task_assigned`, `agent_task_refused`, `agent_human_input_requested`, `agent_escalated`, `agent_conflict_marked`, `agent_progress_declared`, `agent_goal_completed`, `agent_supervisor_verdict`, `agent_decision_logged`, `agent_conversation_finished` |
| Miscellaneous | `cost_update`, `doom_loop_detected`, `doom_loop_intervened`, `suggestions`, `title_generated`, `progress`, `session_forked`, `session_merged`, `conversation_participant_joined`, `conversation_participant_left` |

## Frontend Handling

Frontend event handling is intentionally split:

- `web/src/services/agent/messageRouter.ts` routes WebSocket messages to callbacks.
- `web/src/utils/sseEventAdapter.ts` normalizes historical and current event envelopes.
- `web/src/stores/sandbox.ts` handles sandbox and artifact events.
- `web/src/stores/agent/*` updates conversation, timeline, streaming, HITL, and canvas state.
- Timeline presentation is under `web/src/components/agent/`.

Because event handlers are spread across these files, do not rely on a static
"frontend handled count" in this document. Verify handling with source search when adding or
changing an event.

## Update Checklist

When adding or changing an event:

1. Add the value to `AgentEventType` in `src/domain/events/types.py`.
2. Add or update the `AgentDomainEvent` subclass in `src/domain/events/agent_events.py`.
3. Update conversion/persistence behavior if payload shape changes.
4. Update frontend routing/adaptation if the event is user-visible.
5. Add tests for payload shape and frontend behavior where practical.
6. Update this document if the event creates a new category or changes a public contract.

## Quick Checks

```bash
# Count AgentEventType values
awk 'BEGIN{in_enum=0} /^class AgentEventType/{in_enum=1; next} /^# =/{if(in_enum) exit} in_enum && /^[[:space:]]+[A-Z0-9_]+ = "/{count++} END{print count}' src/domain/events/types.py

# Find frontend handlers for one event
rg -n "workspace_plan_updated|subagent_started|artifact_ready" web/src
```
