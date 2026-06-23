# Documentation Archive Index

Historical planning, migration, and design documents have been grouped under
`docs/archive/{topic}/`. These files are point-in-time records: useful for
rationale and migration history, but not current implementation references.
Current code is the source of truth when an archived document disagrees with
the repository.

For maintained docs, start at [../README.md](../README.md).

Last updated: 2026-06-22.

## Maintained Docs

- Current docs index: [../README.md](../README.md)
- Current architecture: [../architecture/ARCHITECTURE.md](../architecture/ARCHITECTURE.md)
- Current API overview: [../api-reference.md](../api-reference.md)
- Current tools overview: [../TOOLS.md](../TOOLS.md)
- Current frontend docs: [../../web/docs/README.md](../../web/docs/README.md)

## Historical Clusters

### agent-framework/ — Agent framework and runtime history

[agent-framework/](agent-framework/)

| File | Topic |
|---|---|
| [design-decisions.md](agent-framework/design-decisions.md) | Foundational agent framework design decisions. |
| [agent-execution-id.md](agent-framework/agent-execution-id.md) | Agent execution ID scheme introduction. |
| [agent-execution-id-progress.md](agent-framework/agent-execution-id-progress.md) | Progress notes for the agent execution ID rollout. |
| [memstack-agent-framework-design.md](agent-framework/memstack-agent-framework-design.md) | MemStack agent backend framework design. |
| [memstack-agent-ui-framework-design.md](agent-framework/memstack-agent-ui-framework-design.md) | MemStack agent UI framework design. |
| [architect-reply-to-code-review.md](agent-framework/architect-reply-to-code-review.md) | Architect response to agent framework code review. |

### agent-ui/ — Agent UI rendering history

[agent-ui/](agent-ui/)

| File | Topic |
|---|---|
| [agent-chat-timeline-rendering-plan.md](agent-ui/agent-chat-timeline-rendering-plan.md) | Agent chat timeline rendering plan. |

### sandbox/ — Sandbox integration and refactor history

[sandbox/](sandbox/)

| File | Topic |
|---|---|
| [sandbox-integration-plan.md](sandbox/sandbox-integration-plan.md) | Sandbox integration plan. |
| [sandbox-integration-remaining-plan.md](sandbox/sandbox-integration-remaining-plan.md) | Remaining sandbox integration work. |
| [sandbox-refactor-plan.md](sandbox/sandbox-refactor-plan.md) | Sandbox refactor plan. |
| [sandbox-frontend-integration-summary.md](sandbox/sandbox-frontend-integration-summary.md) | Sandbox frontend integration summary. |
| [sandbox-desktop-shell-integration-plan.md](sandbox/sandbox-desktop-shell-integration-plan.md) | Sandbox desktop shell integration plan. |
| [INTEGRATION_COMPLETE.md](sandbox/INTEGRATION_COMPLETE.md) | Sandbox integration completion record. |
| [frontend-integration-analysis.md](sandbox/frontend-integration-analysis.md) | Frontend integration analysis for sandbox. |

### plan-mode/ — Plan mode history

[plan-mode/](plan-mode/)

| File | Topic |
|---|---|
| [plan-mode-assessment-report.md](plan-mode/plan-mode-assessment-report.md) | Plan mode assessment report. |
| [plan-mode-fix-summary.md](plan-mode/plan-mode-fix-summary.md) | Plan mode fix summary. |
| [plan-mode-integration.md](plan-mode/plan-mode-integration.md) | Plan mode integration notes. |
| [plan-mode-ui-integration-plan.md](plan-mode/plan-mode-ui-integration-plan.md) | Plan mode UI integration plan. |
| [plan-mode.md](plan-mode/plan-mode.md) | Early plan mode design notes (superseded by maintained `architecture/plan-mode.md`). |

### mcp/ — MCP protocol/UI history

[mcp/](mcp/)

| File | Topic |
|---|---|
| [MCP_PROTOCOL_IMPLEMENTATION_SUMMARY.md](mcp/MCP_PROTOCOL_IMPLEMENTATION_SUMMARY.md) | MCP protocol implementation summary. |
| [MCP_UI_MIGRATION_SUMMARY.md](mcp/MCP_UI_MIGRATION_SUMMARY.md) | MCP UI migration summary. |

### frontend/ — Frontend plan/migration history

[frontend/](frontend/)

| File | Topic |
|---|---|
| [frontend-refactor-plan.md](frontend/frontend-refactor-plan.md) | Frontend refactor plan. |
| [frontend-sandbox-migration.md](frontend/frontend-sandbox-migration.md) | Frontend sandbox migration guide. |
| [implementation-plan-sse-adapter-integration.md](frontend/implementation-plan-sse-adapter-integration.md) | SSE adapter integration plan (live chat is now WebSocket-based). |
| [implementation-plan-timeline-event-unification.md](frontend/implementation-plan-timeline-event-unification.md) | Timeline event unification plan. |
| [phase2-plan-mode-store-split.md](frontend/phase2-plan-mode-store-split.md) | Plan-mode store split, phase 2. |

### architecture/ — Architecture proposals and migration records

[architecture/](architecture/)

| File | Topic |
|---|---|
| [MULTI_AGENT.md](architecture/MULTI_AGENT.md) | Multi-agent design notes. |
| [multi-agent-proposal.md](architecture/multi-agent-proposal.md) | Multi-agent proposal. |
| [SANDBOX_FIRST_ARCHITECTURE.md](architecture/SANDBOX_FIRST_ARCHITECTURE.md) | Sandbox-first architecture proposal. |
| [plan_mode_optimization_proposal.md](architecture/plan_mode_optimization_proposal.md) | Plan mode optimization proposal. |
| [PLUGIN_TOOL_PIPELINE_FIX.md](architecture/PLUGIN_TOOL_PIPELINE_FIX.md) | Plugin tool pipeline fix record. |
| [PLUGIN_TOOL_SUBSYSTEM_REFACTORING_PROPOSAL.md](architecture/PLUGIN_TOOL_SUBSYSTEM_REFACTORING_PROPOSAL.md) | Plugin tool subsystem refactoring proposal. |
| [plugin-architecture-evolution-plan.md](architecture/plugin-architecture-evolution-plan.md) | Plugin architecture evolution plan. |

### cyber-workspace/ — Cyber workspace history

[cyber-workspace/](cyber-workspace/)

| File | Topic |
|---|---|
| [cyber-office-3d-architecture.md](cyber-workspace/cyber-office-3d-architecture.md) | Cyber office 3D architecture design. |

### scene/ — Scene/tool implementation history

[scene/](scene/)

| File | Topic |
|---|---|
| [sandbox-mcp-tools-implementation.md](scene/sandbox-mcp-tools-implementation.md) | Sandbox MCP tools implementation notes. |
| [tools.md](scene/tools.md) | Early scene/tool reference notes. |

## Related Archives

- Web-only historical audits still live under [../../web/docs/](../../web/docs/).
- Sandbox MCP server phase records still live under [../../sandbox-mcp-server/docs/](../../sandbox-mcp-server/docs/).

When updating current behavior, edit maintained docs first. Add a historical note only when
the implementation rationale matters.
