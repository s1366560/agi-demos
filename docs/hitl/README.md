# HITL (Human-in-the-Loop)

HITL lets an agent pause and request human input before it continues. The current
implementation is Ray Actor + Redis Streams + PostgreSQL persistence. It does not use
Temporal.

Last checked against code: 2026-06-23.

## Request Types

| Type | Purpose | Example response payload |
|---|---|---|
| `clarification` | Clarify user intent or missing parameters | `{ "answer": "Use staging" }` |
| `decision` | Choose one branch or option | `{ "decision": "proceed" }` |
| `env_var` | Provide required environment variables | `{ "values": { "OPENAI_API_KEY": "..." }, "save": true }` |
| `permission` | Allow or deny a sensitive action | `{ "action": "allow", "remember": false }` |
| `a2ui_action` | Respond to an interactive A2UI component action | component-specific payload |

## Current Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Web as Web Console
    participant WS as /api/v1/agent/ws
    participant Actor as ProjectAgentActor
    participant DB as PostgreSQL
    participant Redis as Redis Stream
    participant Router as HITLStreamRouterActor

    User->>Web: Send agent message
    Web->>WS: send_message
    WS->>Actor: start/continue chat
    Actor->>DB: persist HITL request
    Actor->>WS: emit clarification_asked / decision_asked / env_var_requested / permission_asked / a2ui_action_asked
    User->>Web: Submit response
    Web->>WS: *_respond message
    Web->>DB: POST /api/v1/agent/hitl/respond fallback/recovery path
    DB->>Redis: hitl:response:{tenant_id}:{project_id}
    Redis->>Router: response consumed
    Router->>Actor: continue_chat(request_id, response)
    Actor->>WS: continue events and completion
```

The REST endpoints are still important for refresh/recovery and explicit response/cancel
paths. Live chat itself is WebSocket-based.

`a2ui_action` requests are the HITL branch used by interactive A2UI/canvas surfaces; the
WebSocket response message is `a2ui_action_respond`.

## Backend Components

| Component | Path | Responsibility |
|---|---|---|
| HITL domain types | `src/domain/model/agent/hitl/hitl_types.py` | HITL type/status/request primitives and pending exception. |
| Request entity | `src/domain/model/agent/hitl_request.py` | Persistable HITL request model. |
| Handler | `src/infrastructure/agent/hitl/ray_hitl_handler.py` | Persists requests and raises the pause signal. |
| State helpers | `src/infrastructure/agent/hitl/state_store.py`, `coordinator.py` | Redis/Postgres state support and local coordination. |
| Router actor | `src/infrastructure/agent/actor/hitl_router_actor.py` | Consumes response stream and resumes project actors. |
| Project actor | `src/infrastructure/agent/actor/project_agent_actor.py` | Owns execution and resume paths. |
| REST router | `src/infrastructure/adapters/primary/web/routers/agent/hitl.py` | Pending/response/cancel endpoints. |
| WebSocket handlers | `src/infrastructure/adapters/primary/web/websocket/handlers/hitl_handler.py` | Live HITL response messages. |

## REST Endpoints

Base path:

```text
/api/v1/agent/hitl
```

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/conversations/{conversation_id}/pending` | List pending requests for a conversation. |
| `GET` | `/projects/{project_id}/pending?limit=50` | List pending requests for a project. |
| `POST` | `/respond` | Submit any HITL response. |
| `POST` | `/cancel` | Cancel a pending request. |

See [api-reference.md](api-reference.md) for schemas and examples.

## Design Rules

- Authorize by tenant/project/conversation before showing or accepting a response.
- Persist the answer before publishing to Redis; failed publish returns success with a
  delivery-pending message.
- `env_var` supports exactly one of `values`, `cancelled`, or `timeout`.
- Secrets must be redacted in logs and must use encrypted response fields where required by
  the tool/runtime path.
- Keep HITL events in sync with `src/domain/events/types.py`.

## Related Docs

| Doc | Purpose |
|---|---|
| [api-reference.md](api-reference.md) | REST endpoint contract. |
| [request-types.md](request-types.md) | Type-specific request/response fields. |
| [frontend-guide.md](frontend-guide.md) | Frontend state and UI handling. |
| [ray-integration.md](ray-integration.md) | Ray actor resume and recovery details. |
| [architecture.md](architecture.md) | Component architecture and state flow. |
| [troubleshooting.md](troubleshooting.md) | Operational checks. |
