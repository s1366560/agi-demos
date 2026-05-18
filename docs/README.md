# MemStack Documentation

This directory contains both maintained documentation and historical design/planning
artifacts. Current code is the source of truth when a historical document disagrees with
the repository.

Last checked against code: 2026-05-18.

## Maintained Entry Points

| Topic | Document | Source checked |
|---|---|---|
| Project overview | [../README.md](../README.md) | `Makefile`, `pyproject.toml`, `web/package.json`, FastAPI router registration |
| Current architecture | [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | `src/domain`, `src/application`, `src/infrastructure`, `web/src` |
| API route overview | [api-reference.md](api-reference.md) | `src/infrastructure/adapters/primary/web/main.py` and router modules |
| Agent tools | [TOOLS.md](TOOLS.md) | `src/infrastructure/agent/tools`, `sandbox-mcp-server` |
| Agent event types | [agent-event-types.md](agent-event-types.md) | `src/domain/events/types.py`, `web/src/utils/sseEventAdapter.ts` |
| CLI | [CLI.md](CLI.md) | `sdk/memstack_cli` |
| HITL | [hitl/README.md](hitl/README.md) | `src/infrastructure/agent/hitl`, `src/infrastructure/agent/actor` |
| Type safety | [TYPE_SAFETY.md](TYPE_SAFETY.md) | `pyproject.toml`, `pyrightconfig.json`, web TypeScript config |
| Python SDK | [../sdk/python/README.md](../sdk/python/README.md) | `sdk/python/memstack` |
| Web console | [../web/README.md](../web/README.md) | `web/package.json`, `web/src/App.tsx`, `web/src/services` |

## Architecture And Runtime Docs

| Area | Current docs |
|---|---|
| Architecture | [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md), [architecture/README.md](architecture/README.md) |
| Multi-agent and pool notes | [architecture/MULTI_AGENT.md](architecture/MULTI_AGENT.md), [architecture/AGENT_POOL.md](architecture/AGENT_POOL.md) |
| Plan mode and workspace planning | [plan-mode.md](plan-mode.md), [architecture/plan-mode.md](architecture/plan-mode.md), [plan-mode-integration.md](plan-mode-integration.md) |
| Sandbox | [sandbox-unified-architecture.md](sandbox-unified-architecture.md), [sandbox-mcp-server/README.md](../sandbox-mcp-server/README.md) |
| MCP | [mcp_protocol_implementation.md](mcp_protocol_implementation.md), [mcp_protocol_quick_reference.md](mcp_protocol_quick_reference.md) |
| Events | [agent-event-types.md](agent-event-types.md), [architecture/event-system-timeline.md](architecture/event-system-timeline.md) |
| HITL | [hitl/README.md](hitl/README.md) |

## Historical Artifacts

Files with names such as `*-plan.md`, `*-proposal.md`, `*-summary.md`, `*-report.md`,
`*-migration.md`, `*-progress.md`, and `*-complete.md` are point-in-time records. They are
useful for rationale and migration history, but they should not be treated as current
implementation references unless this index links to them as maintained docs.

Historical files are intentionally left at their original paths to avoid breaking inbound
links. Use [archive/README.md](archive/README.md) for the grouped archive index.

Examples:

- Planning records: [PLAN.md](PLAN.md), [frontend-refactor-plan.md](frontend-refactor-plan.md),
  [sandbox-refactor-plan.md](sandbox-refactor-plan.md)
- Migration/status summaries:
  [MCP_UI_MIGRATION_SUMMARY.md](MCP_UI_MIGRATION_SUMMARY.md),
  [REACT_AGENT_REFACTOR_SUMMARY.md](REACT_AGENT_REFACTOR_SUMMARY.md),
  [INTEGRATION_COMPLETE.md](INTEGRATION_COMPLETE.md)
- Reviews/audits:
  [frontend-backend-interface-review.md](frontend-backend-interface-review.md),
  [opencode-tools-audit.md](opencode-tools-audit.md),
  [web/AGENT_COMPONENT_AUDIT.md](web/AGENT_COMPONENT_AUDIT.md)

## Documentation Maintenance Rules

1. Update [../README.md](../README.md) when setup, commands, service URLs, core architecture,
   or live transport changes.
2. Update [api-reference.md](api-reference.md) when routers are added, removed, renamed, or
   moved under a different prefix.
3. Update [agent-event-types.md](agent-event-types.md) when
   `src/domain/events/types.py` changes.
4. Update [TOOLS.md](TOOLS.md) when built-in tools, sandbox tools, or plugin runtime tool
   loading changes.
5. Add historical notes to new planning documents instead of presenting them as current
   architecture.

## Quick Consistency Checks

```bash
rg -n "ARCHITECTURE.md|api-reference.md|/agent/chat|React 18|Vite 6|plan_enter" README.md docs web sdk
npx gitnexus status
```

The first command catches common stale claims. The second confirms that the code
intelligence index matches the current commit before relying on graph-derived facts.
