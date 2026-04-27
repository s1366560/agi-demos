"""Canonical metadata key constants for workspace autonomy.

Historically these keys were scattered as magic strings across
``workspace_goal_runtime``, ``worker_report/``, ``adjudicator/`` and the
dispatcher — 30+ references with subtle typos and inconsistent casing. This
module centralizes them so:

* typos become import errors,
* renames become single-point changes,
* readers can discover the vocabulary by importing this module.

Conventions
-----------
* **Writers** SHOULD import from this module (e.g. ``metadata[KEY] = ...``).
* **Readers** MAY continue using bare string literals in hot loops for now;
  migration is incremental. New code MUST use the constants.
* All keys are ``Final[str]`` so mypy/pyright refuses ``=`` to a Literal mismatch.

The string values must never change without a matching data migration —
existing persisted ``WorkspaceTask.metadata`` payloads already contain them.
"""

from __future__ import annotations

from typing import Final

# --- Identity & provenance -------------------------------------------------

ROOT_GOAL_TASK_ID: Final[str] = "root_goal_task_id"
"""ID of the root goal task this subtask is scoped under."""

WORKSPACE_AGENT_BINDING_ID: Final[str] = "workspace_agent_binding_id"
"""Workspace-scoped agent binding id preserved alongside assignment projections."""

TASK_ROLE: Final[str] = "task_role"
"""Semantic role tag on a task (for example ``"goal_root"`` or ``"execution_task"``)."""

LINEAGE_SOURCE: Final[str] = "lineage_source"
"""Where a task was derived from (e.g. ``"decomposer"``, ``"replan"``)."""

DERIVED_FROM_INTERNAL_PLAN_STEP: Final[str] = "derived_from_internal_plan_step"
"""Step id in the internal plan that produced this execution task."""

WORKSPACE_PLAN_ID: Final[str] = "workspace_plan_id"
"""Durable V2 ``Plan.id`` that authored this workspace task projection."""

WORKSPACE_PLAN_NODE_ID: Final[str] = "workspace_plan_node_id"
"""Durable V2 ``PlanNode.id`` that authored this workspace task projection."""

AUTONOMY_SCHEMA_VERSION_KEY: Final[str] = "autonomy_schema_version"
"""Schema version key for validator forward-compat; see ``autonomy_schema.py``."""

WORKSPACE_HARNESS: Final[str] = "workspace_harness"
"""Long-running-agent harness contract attached to a workspace root goal."""

# --- State machine buckets -------------------------------------------------

EXECUTION_STATE: Final[str] = "execution_state"
"""Nested dict holding transient execution status (attempt ids, timestamps)."""

REMEDIATION_STATUS: Final[str] = "remediation_status"
"""Current remediation lifecycle phase (e.g. ``"pending_replan"``, ``"blocked"``)."""

REMEDIATION_SUMMARY: Final[str] = "remediation_summary"
"""Human-readable note set when autonomy requests human review / gives up."""

REPLAN_ATTEMPT_COUNT: Final[str] = "replan_attempt_count"
"""How many replan cycles this root goal has consumed."""

LAST_REPLAN_AT: Final[str] = "last_replan_at"
"""ISO-8601 timestamp of the most recent replan."""

# --- Worker/attempt bookkeeping -------------------------------------------

CURRENT_ATTEMPT_ID: Final[str] = "current_attempt_id"
"""The active ``WorkspaceTaskSessionAttempt.id`` for a worker task."""

CURRENT_ATTEMPT_WORKER_BINDING_ID: Final[str] = "current_attempt_worker_binding_id"
"""Workspace-scoped binding id for the worker on the active attempt."""

PENDING_LEADER_ADJUDICATION: Final[str] = "pending_leader_adjudication"
"""True while a worker report is waiting for leader verdict."""

LAST_WORKER_REPORT_SUMMARY: Final[str] = "last_worker_report_summary"
"""Most recent worker report payload (dict) used by the adjudicator."""

LAST_LEADER_ADJUDICATION_STATUS: Final[str] = "last_leader_adjudication_status"
"""Most recent leader verdict value (``"completed"``/``"blocked"``/...)."""


__all__ = [
    "AUTONOMY_SCHEMA_VERSION_KEY",
    "CURRENT_ATTEMPT_ID",
    "CURRENT_ATTEMPT_WORKER_BINDING_ID",
    "DERIVED_FROM_INTERNAL_PLAN_STEP",
    "EXECUTION_STATE",
    "LAST_LEADER_ADJUDICATION_STATUS",
    "LAST_REPLAN_AT",
    "LAST_WORKER_REPORT_SUMMARY",
    "LINEAGE_SOURCE",
    "PENDING_LEADER_ADJUDICATION",
    "REMEDIATION_STATUS",
    "REMEDIATION_SUMMARY",
    "REPLAN_ATTEMPT_COUNT",
    "ROOT_GOAL_TASK_ID",
    "TASK_ROLE",
    "WORKSPACE_AGENT_BINDING_ID",
    "WORKSPACE_HARNESS",
    "WORKSPACE_PLAN_ID",
    "WORKSPACE_PLAN_NODE_ID",
]
