# agent/processor/ — SessionProcessor & Tool Execution

## Purpose
- Implements the Think-Act-Observe cycle that drives agent reasoning
- Handles tool execution, artifact extraction, event emission, and HITL coordination

## Key Files

| File | Role |
|------|------|
| `processor.py` | `SessionProcessor` — main ReAct loop, tool dispatch, state machine |
| `artifact_handler.py` | `ArtifactHandler` — extracts artifacts from tool output, S3 upload, event emission |
| `factory.py` | `ProcessorFactory` (frozen dataclass) — creates SessionProcessor for main/subagent |
| `run_context.py` | Per-run context (conversation_id, message_id, abort signal) |
| `goal_evaluator.py` | `GoalEvaluator` — checks task completion after no-tool steps |
| `hitl_coordinator.py` | HITL request handling (clarification, decision, env_var, permission) |

## SessionProcessor State Machine
```
IDLE -> THINKING -> ACTING -> OBSERVING -> THINKING (loop)
                 -> WAITING_CLARIFICATION
                 -> WAITING_DECISION
                 -> RETRYING
                 -> COMPLETED / ERROR
```

## process() Main Loop
1. Check abort signal
2. `_process_step()` — create Message, prepare tools, create LLMStream
3. Stream events: TEXT_DELTA, TEXT_DONE, REASONING_DELTA, TOOL_CALL_START, TOOL_CALL_DELTA, TOOL_CALL_DONE
4. On TOOL_CALL_DONE: execute tool via `tool_def.execute()`
5. Post-execute: consume pending events from `tool_def._tool_instance`
6. Yield domain events (AgentTaskListUpdatedEvent, etc.)
7. Evaluate goal — GoalEvaluator checks if done
8. Append tool results to context, loop back to step 1

## Artifact Handling Flow
- `ArtifactHandler.extract()` scans tool output for MCP-style content blocks
- Binary data sanitized before storage
- Upload to S3 runs in background thread (non-blocking)
- Event sequence: `artifact_created` -> (upload completes) -> `artifact_ready`
- Canvas-displayable content detected and flagged for frontend rendering

## ProcessorFactory
- Frozen dataclass — immutable after creation
- Creates SessionProcessor with shared deps (LLM client, memory, tools)
- SubAgent processors get model inheritance: subagent model config -> fallback to parent model
- Resolves tool sets per-agent (main agent gets full set, subagents get filtered)

## Command Interception
- Slash commands (e.g., `/plan`, `/skill`) intercepted before LLM call
- Handled by command handlers, not the ReAct loop
- Returns early without consuming LLM tokens

## Gotchas
- `tool_provider` callback refreshes tools mid-conversation — tool map can change between steps
- DoomLoopDetector resets on successful tool output, NOT on tool call count
- RetryPolicy applies to LLM failures, NOT tool failures (tools handle own retries)
- CostTracker accumulates across steps — check before each LLM call for budget enforcement
- GoalEvaluator triggers no-progress counter after consecutive no-tool steps
