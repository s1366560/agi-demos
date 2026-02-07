# HITL Architecture Refactoring Plan

## Problem Statement

Current HITL uses exception-based flow control (`HITLPendingException`) to pause the agent ReAct loop.
This creates several fundamental problems:

1. **Fragile state management**: The exception unwinds the entire call stack, losing all local state.
   Resume requires reconstructing context via `_preinjected_response` + tool result injection — two
   redundant mechanisms that cause bugs (second HITL reuses first response).
2. **No clean consecutive HITL support**: Each resume creates a fresh `execute_chat()` call with
   `hitl_response` baked in. The processor can't distinguish "first tool on resume" from "new tool".
3. **Dual event delivery**: `hitl_tool_handler` yields domain events AND `_execute_hitl_request`
   publishes to unified event bus — two separate event paths for the same HITL.
4. **Hard to extend**: Adding a new HITL type requires changes in 8+ files.

## Proposed Architecture: Cooperative Yield (AsyncIO Event-Based)

Replace `HITLPendingException` with an **asyncio.Future-based cooperative yield** inside the ReAct
loop. The processor pauses at the tool call site (without unwinding the stack), waits for a Future
to be resolved, then continues in-place.

### Core Concept

```
BEFORE (exception-based):
  processor.process() → tool → raise HITLPendingException
    → unwind stack → save state to Redis → exit
    → user responds → continue_project_chat() → new execute_chat() → new processor
    → inject preinjected_response + tool result → LLM sees result → continues

AFTER (future-based):
  processor.process() → tool → create Future, yield hitl_asked event
    → processor loop yields hitl_asked event to caller
    → caller sees hitl_asked, saves state, waits
    → user responds → resolve Future with response
    → tool call returns response value → processor continues in same loop
```

### Key Benefits

1. **No stack unwinding** — the processor stays alive, all local state preserved
2. **No preinjected_response** — eliminate the entire mechanism and its bugs
3. **No dual tool result injection** — tool gets result directly from Future
4. **Clean consecutive HITL** — each HITL tool independently creates and awaits its own Future
5. **Single event path** — HITL events flow through processor like any other event
6. **Easy to extend** — new HITL type = new strategy + new tool, no plumbing changes

### Architecture Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  L1: HITLCoordinator (new)                                       │
│  - Manages pending Futures                                       │
│  - resolve(request_id, response) → sets Future result            │
│  - request(type, data) → creates Future, returns awaitable       │
│  - Replaces RayHITLHandler preinjection + _execute_hitl_request  │
├──────────────────────────────────────────────────────────────────┤
│  L2: HITL Tool Handlers (simplified)                             │
│  - yield AgentHITLAskedEvent                                     │
│  - result = await coordinator.request(type, data)                │
│  - yield AgentHITLAnsweredEvent                                  │
│  - No HITLPendingException                                       │
├──────────────────────────────────────────────────────────────────┤
│  L3: Processor (unchanged loop, new HITL handling)               │
│  - process() loop runs tools as before                           │
│  - HITL tool awaits Future inside _execute_tool                  │
│  - process() yields hitl_asked event to caller                   │
│  - Caller keeps process() generator alive (not unwound)          │
├──────────────────────────────────────────────────────────────────┤
│  L4: Execution Layer (simplified resume)                         │
│  - execute_project_chat() keeps generator alive during HITL      │
│  - No continue_project_chat() needed for same-process resume     │
│  - State save only for crash recovery, not for normal flow       │
│  - Redis listener resolves coordinator Future directly           │
└──────────────────────────────────────────────────────────────────┘
```

### Critical Constraint: Generator Yield

The processor is an `async generator`. When a HITL tool needs to pause:

1. Tool calls `coordinator.request()` which creates an `asyncio.Future` and returns a
   `HITLPendingToken` (not an exception)
2. Tool handler yields `AgentHITLAskedEvent` with the token
3. Processor's `_execute_tool` sees the token, yields the event upward
4. Processor's `_process_step` yields the event upward (generator stays alive)
5. `process()` loop yields the event to caller
6. Caller (execution.py) receives the event, saves state for crash recovery
7. Caller publishes event to Redis stream for WebSocket
8. Meanwhile, Redis HITL response listener calls `coordinator.resolve(request_id, data)`
9. The Future resolves → tool handler continues → returns result
10. Processor continues the ReAct loop naturally

**Key insight**: The processor generator stays suspended at the `yield` point inside
`_process_step`. It's NOT unwound. When the Future resolves, the tool completes, the step
finishes, and the generator naturally produces more events.

BUT — there's a problem: the processor is an `AsyncIterator` consumed by `async for`. The
consumer needs to keep pulling. If execution.py stops pulling when it sees `hitl_asked`, the
generator suspends but the tool's Future won't resolve because the event loop is blocked.

**Solution**: The tool handler needs to yield the `hitl_asked` event AND THEN await the Future.
But in a generator function, you can't `await` and `yield` at the same time in the natural flow.

**Revised approach**: Use a **side-channel** pattern:
- Tool creates Future, stores in coordinator
- Tool yields `AgentHITLAskedEvent` (generator yields this to caller)
- Caller receives it, does bookkeeping
- Caller continues pulling from generator (the `async for` continues)
- Next iteration of generator, tool is still in `_execute_tool`, now awaits Future
- Generator suspends on the await (not a yield), consumer's `async for` blocks
- Redis listener resolves Future → generator resumes → yields more events

This works because `async for` on an `AsyncIterator` will block on the `__anext__` call
while the generator is awaiting the Future. The event loop is free to process the Redis
listener callback that resolves the Future.

## Workplan

### Phase 1: HITLCoordinator (core mechanism)
- [ ] 1.1 Create `src/infrastructure/agent/hitl/coordinator.py`
  - `HITLCoordinator` class with `request()` and `resolve()` methods
  - `request(hitl_type, request_data, timeout) -> asyncio.Future`
  - `resolve(request_id, response_data) -> bool`
  - Timeout handling with `asyncio.wait_for`
  - Persist request to DB (reuse `_persist_hitl_request`)
  - Emit to unified event bus (reuse `_emit_hitl_sse_event`)

### Phase 2: Refactor HITL tool handlers
- [ ] 2.1 Update `hitl_tool_handler.py`
  - Replace `handler.request_*()` + `HITLPendingException` catch
    with `coordinator.request()` await
  - Keep yielding domain events (asked/answered)
  - Remove `peek_preinjected_response` usage
  - Remove `HITLPendingException` re-raise

### Phase 3: Refactor processor
- [ ] 3.1 Update `processor.py`
  - Remove `HITLPendingException` catch block (line 416-448)
  - Remove preinjected response clearing logic (line 376-390)
  - Pass coordinator to `_get_hitl_handler` or replace handler entirely
  - `_handle_*_tool` methods use coordinator instead of handler

### Phase 4: Refactor RayHITLHandler
- [ ] 4.1 Simplify `ray_hitl_handler.py`
  - Remove `_preinjected_response` mechanism entirely
  - Remove `_execute_hitl_request` (replaced by coordinator)
  - Remove `peek_preinjected_response`
  - Keep strategy pattern for request creation and response extraction
  - Handler becomes thin wrapper delegating to coordinator

### Phase 5: Refactor execution layer
- [ ] 5.1 Update `execution.py`
  - `execute_project_chat`: detect `hitl_asked` events from stream,
    save state for crash recovery, but keep generator alive
  - `continue_project_chat`: simplify — only needed for crash recovery
    (process restart), not for normal HITL flow
  - Remove `hitl_response_for_agent` / `_preinjected_response` injection
  - Wire coordinator's `resolve()` to Redis HITL response listener

### Phase 6: Wire response path
- [ ] 6.1 Update response consumption
  - `local_resume_consumer.py`: call `coordinator.resolve()` instead of
    `continue_project_chat()`
  - WebSocket `hitl_handler.py`: call `coordinator.resolve()` directly
  - Remove bridge task complexity (no longer needed for same-process)
  - Keep `continue_project_chat` only for cross-process crash recovery

### Phase 7: Cleanup and tests
- [ ] 7.1 Remove dead code
  - Remove `_preinjected_response` from all files
  - Remove redundant `_format_hitl_response_as_tool_result`
  - Remove `hitl_response` parameter from `execute_chat`/`stream`
- [ ] 7.2 Update tests
  - Update `test_ray_hitl_handler.py` for new coordinator
  - Add consecutive HITL test
  - Add timeout test
- [ ] 7.3 Lint and verify

## Risk Assessment

### Low Risk
- Strategy pattern (temporal_hitl_handler.py) unchanged
- Domain types (hitl_types.py) unchanged except removing HITLPendingException usage
- Frontend unchanged (same events, same response API)
- WebSocket handlers mostly unchanged

### Medium Risk
- Execution layer refactoring — need to handle crash recovery path
- Coordinator Future lifecycle — must handle timeout, cancel, process restart
- Generator suspension semantics — must verify async for + await interaction

### High Risk (mitigation needed)
- **Cross-process restart**: If the process dies while waiting on a Future, the coordinator
  state is lost. Mitigation: keep state save to Redis/Postgres, and keep
  `continue_project_chat` as the crash recovery path. On restart, detect pending HITL
  from DB and recreate coordinator state.
- **Concurrent HITL**: If LLM calls two HITL tools in parallel (unlikely but possible),
  each creates its own Future — this naturally works with the coordinator pattern.

## Notes

- HITLPendingException is kept in domain types for backward compatibility but no longer
  raised in the main flow
- The strategy pattern in temporal_hitl_handler.py is preserved — it handles request
  creation and response extraction cleanly
- Frontend changes: NONE — same SSE events, same REST response API
- The coordinator pattern is similar to how Temporal Signals work, but without Temporal
