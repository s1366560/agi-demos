# Domain Events - Agent Event System

## Event Flow

```
Tool._pending_events → Processor.consume → AgentDomainEvent → EventConverter → SSE dict → Redis → WebSocket → Frontend
```

## Key Files

| File | Role |
|------|------|
| `types.py` | **SINGLE SOURCE OF TRUTH** for all event types. `AgentEventType` enum (70+ values), `EventCategory` enum |
| `agent_events.py` | All `AgentDomainEvent` subclasses (Pydantic models). Each has `to_event_dict()` for SSE serialization |
| `event_dicts.py` | TypedDict definitions for SSE event dict shape (`SSEEventDict`) |
| `envelope.py` | Event envelope for wrapping events with metadata |
| `serialization.py` | Event serialization/deserialization helpers |
| `event_serializer.py` | Serializer implementation |
| `registry.py` | Event type registry for dynamic dispatch |

## Event Categories (from types.py)

- `AGENT` — execution events (thought, act, observe, text, plan, step, task)
- `HITL` — human-in-the-loop (clarification, decision, env_var, permission)
- `SANDBOX` — sandbox lifecycle (sandbox_ready, desktop_ready, terminal_*)
- `SYSTEM` — system-level (heartbeat, connection)
- `MESSAGE` — message events (user_message, assistant_message)

## Adding a New Event Type

1. Add enum value to `AgentEventType` in `types.py`
2. Create `AgentDomainEvent` subclass in `agent_events.py` with `to_event_dict()`
3. Update `__all__` export list in `agent_events.py`
4. Update frontend `AgentEventType` (auto-generated via `scripts/generate_event_types.py`)
5. Add handler in frontend `streamEventHandlers.ts`

## Gotchas

- Event type values use flat naming ("thought", "act") — NOT namespaced ("agent.thought")
- `AgentDomainEvent` uses Pydantic `BaseModel` (not dataclass) with `frozen = True`
- `to_event_dict()` excludes `event_type` and `timestamp` from data payload, adds them at top level
- The `scripts/generate_event_types.py` script auto-generates TypeScript types — do NOT edit `eventTypes.ts` manually
- 70+ event types exist — check `types.py` before adding duplicates
