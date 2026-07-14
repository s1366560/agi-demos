# Architecture Docs

Use [ARCHITECTURE.md](ARCHITECTURE.md) as the maintained architecture map. The
cross-runtime ownership boundary and repair sequence are tracked in
[CROSS_RUNTIME_REMEDIATION_PLAN.md](CROSS_RUNTIME_REMEDIATION_PLAN.md).

The other files in this directory are useful design history. Many are proposals, migration
plans, or implementation timelines and should be read as point-in-time records unless they
are explicitly linked from the maintained map.

## Current Maintained Map

- [ARCHITECTURE.md](ARCHITECTURE.md) - current backend/frontend/runtime architecture.
- [CROSS_RUNTIME_REMEDIATION_PLAN.md](CROSS_RUNTIME_REMEDIATION_PLAN.md) - current Desktop/Rust/Python/Web repair and parity plan.

## Route Source Map

Use these code files when a design document mentions implemented HTTP or WebSocket behavior:

| Area | Source of truth |
|---|---|
| Agent WebSocket | `src/infrastructure/adapters/primary/web/websocket/router.py` and `websocket/handlers/` |
| Conversation plan/build mode | `src/infrastructure/adapters/primary/web/routers/agent/plans.py` |
| Workspace planning | `src/infrastructure/adapters/primary/web/routers/workspace_plans.py` |
| HITL | `src/infrastructure/adapters/primary/web/routers/agent/hitl.py` and `websocket/handlers/hitl_handler.py` |
| Sandbox | `src/infrastructure/adapters/primary/web/routers/sandbox/` and `project_sandbox.py` |
| MCP | `src/infrastructure/adapters/primary/web/routers/mcp/` |
| Agent pool admin | `src/infrastructure/agent/pool/api/router.py` |

## Historical Or Focused Notes

- [AGENT_POOL.md](AGENT_POOL.md) - agent pool architecture notes.
- [CYBER_WORKSPACE_ARCHITECTURE.md](CYBER_WORKSPACE_ARCHITECTURE.md) - workspace/cyber-office design.
- [event-system-timeline.md](event-system-timeline.md) - event timeline history.
- [plan-mode.md](plan-mode.md) - plan mode design notes.

Historical proposals and migration records that used to live in this directory
(`MULTI_AGENT.md`, `SANDBOX_FIRST_ARCHITECTURE.md`, `PLUGIN_TOOL_*.md`,
`plan_mode_optimization_proposal.md`, `plugin-architecture-evolution-plan.md`,
`multi-agent-proposal.md`) have been archived under
[../archive/architecture/](../archive/architecture/). See
[../archive/README.md](../archive/README.md) for the grouped archive index.
