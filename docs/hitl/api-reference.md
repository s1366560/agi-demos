# HITL API Reference

Base URL:

```text
http://localhost:8000/api/v1/agent/hitl
```

All endpoints require `Authorization: Bearer ms_sk_...`.

Last checked against code: 2026-06-23.

## Response Models

### PendingHITLResponse

```json
{
  "requests": [
    {
      "id": "hitl_request_id",
      "conversation_id": "conversation_id",
      "message_id": "message_id",
      "request_type": "clarification",
      "question": "Which environment should I use?",
      "options": [],
      "context": {},
      "metadata": {},
      "created_at": "2026-05-18T07:00:00Z",
      "expires_at": "2026-05-18T07:05:00Z",
      "status": "pending"
    }
  ],
  "total": 1
}
```

### HumanInteractionResponse

```json
{
  "success": true,
  "message": "Clarification response received"
}
```

## List Pending Requests For A Conversation

```text
GET /conversations/{conversation_id}/pending
```

Example:

```bash
curl "http://localhost:8000/api/v1/agent/hitl/conversations/$CONVERSATION_ID/pending" \
  -H "Authorization: Bearer $API_KEY"
```

The caller must have access to the conversation in the current tenant.

## List Pending Requests For A Project

```text
GET /projects/{project_id}/pending?limit=50
```

Example:

```bash
curl "http://localhost:8000/api/v1/agent/hitl/projects/$PROJECT_ID/pending?limit=50" \
  -H "Authorization: Bearer $API_KEY"
```

The caller must belong to the project.

## Respond To A HITL Request

```text
POST /respond
```

Request body:

```json
{
  "request_id": "hitl_request_id",
  "hitl_type": "clarification",
  "response_data": {
    "answer": "Use staging"
  }
}
```

Valid `hitl_type` values:

| Type | `response_data` shape |
|---|---|
| `clarification` | `{ "answer": "..." }` |
| `decision` | `{ "decision": "option_id" }` |
| `env_var` | `{ "values": { "VAR_NAME": "value" }, "save": true }` |
| `env_var` cancellation | `{ "cancelled": true }` |
| `env_var` timeout | `{ "timeout": true }` |
| `permission` | `{ "action": "allow", "remember": false }` |
| `a2ui_action` | component-specific payload |

Example:

```bash
curl -X POST "http://localhost:8000/api/v1/agent/hitl/respond" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "hitl_request_id",
    "hitl_type": "decision",
    "response_data": {
      "decision": "proceed"
    }
  }'
```

Behavior:

- The request is loaded from PostgreSQL and authorized.
- Expired requests are marked timed out.
- The answer is persisted first.
- The answer is published to `hitl:response:{tenant_id}:{project_id}` for Ray actors.
- If Redis publish fails after persistence, the endpoint returns success with a
  delivery-pending message.

## Cancel A HITL Request

```text
POST /cancel
```

Request body:

```json
{
  "request_id": "hitl_request_id",
  "reason": "No longer needed"
}
```

Example:

```bash
curl -X POST "http://localhost:8000/api/v1/agent/hitl/cancel" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "hitl_request_id",
    "reason": "User cancelled"
  }'
```

Cancellation marks the request cancelled, commits the database transaction, and then attempts
to remove Redis/Postgres resume state.

## WebSocket Response Messages

The web console commonly responds through the agent WebSocket rather than calling REST
directly. Message handlers exist for:

- `clarification_respond`
- `decision_respond`
- `env_var_respond`
- `permission_respond`
- `a2ui_action_respond`

REST remains the recovery and explicit API contract.

## Common Errors

| Status | Meaning |
|---|---|
| 400 | Invalid HITL type or malformed response shape. |
| 403 | User cannot access the conversation or project. |
| 404 | Conversation/project/request was not found. |
| 409 | Request is no longer pending or could not be updated. |
| 500 | Unexpected persistence or delivery error. |
