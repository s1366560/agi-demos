# agent/subagent/ — SubAgent Runtime & Orchestration

## Purpose
- L3 layer: specialized autonomous agents spawned by the main ReAct agent
- Each SubAgent runs an isolated ReAct loop with own context, tools, and SessionProcessor

## Key Files

| File | Role |
|------|------|
| `process.py` | `SubAgentProcess` — creates isolated ReAct loop per SubAgent |
| `background_executor.py` | `BackgroundExecutor` — launches SubAgents as asyncio tasks |
| `context_bridge.py` | `ContextBridge` — condenses parent conversation for SubAgent context |
| `run_registry.py` | `SubAgentRunRegistry` — tracks run states, persistence, lineage |
| `orchestrator.py` | `SubAgentOrchestrator` — routes tasks to appropriate SubAgents |
| `router.py` | `SubAgentRouter` — semantic matching to select SubAgent |
| `executor.py` | `SubAgentExecutor` — synchronous SubAgent execution |
| `task_decomposer.py` | LLM-based task decomposition for multi-SubAgent delegation |
| `parallel_scheduler.py` | Parallel SubAgent execution scheduler |
| `result_aggregator.py` | Combines results from multiple SubAgents |
| `filesystem_loader.py` | Loads SubAgent definitions from `.memstack/agents/*.md` |
| `filesystem_scanner.py` | Scans filesystem for SubAgent definition files |

## SubAgent Execution Flow
```
Main Agent -> SubAgentOrchestrator -> SubAgentRouter (semantic match)
           -> SubAgentExecutor or BackgroundExecutor
           -> SubAgentProcess (isolated ReAct loop)
           -> Result back to main agent
```

## SubAgentProcess Isolation
- Own `SessionProcessor` instance (via `ProcessorFactory`)
- Own context window (condensed from parent via ContextBridge)
- Own tool set (filtered — SubAgents get subset of main agent tools)
- Own system prompt (from SubAgent definition)
- Model inheritance: SubAgent model config -> fallback to parent model

## ContextBridge Token Budget
- SubAgent gets 30% of main agent's token budget
- Max 5 messages from parent conversation
- Max 4000 chars per condensed context
- `build_messages()` constructs: [system, context, memory, task]

## RunRegistry State Machine
```
PENDING -> RUNNING -> COMPLETED
                   -> FAILED
                   -> CANCELLED
                   -> TIMED_OUT
```
- Persistence backends: JSON file, PostgreSQL, SQLite, Redis cache
- File locking for cross-process synchronization
- Terminal run eviction (completed/failed/cancelled runs pruned periodically)
- Lineage tracking: `parent_run_id`, `lineage_root_run_id` for nested SubAgents

## BackgroundExecutor
- Launches SubAgents as asyncio tasks (non-blocking to main agent)
- `StateTracker` monitors lifecycle per task
- Events emitted via callback to parent agent's event stream
- Timeout enforcement per SubAgent run

## Task Decomposition (Multi-SubAgent)
- `TaskDecomposer` uses LLM to split complex tasks into sub-tasks
- `ParallelScheduler` runs independent sub-tasks concurrently
- `ResultAggregator` merges outputs into unified response
- Dependency graph respected — sequential where needed

## SubAgent Definitions
- Stored in `.memstack/agents/*.md` (per-project)
- `FilesystemScanner` discovers definition files
- `FilesystemLoader` parses markdown into SubAgent config (name, description, tools, prompt)
- Hot-reloadable — changes picked up on next SubAgent invocation

## Gotchas
- SubAgent SessionProcessor is separate instance — does NOT share state with parent
- SubAgent tool set is filtered — not all parent tools available
- RunRegistry persistence backend chosen by config — default is JSON file (not Postgres)
- Nested SubAgents supported but lineage depth should be monitored (risk of recursion)
- Background SubAgents may outlive the parent request — cleanup via StateTracker timeout
