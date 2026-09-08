# Cloud knowledge synchronization generation condition

The optional Cloud sync HTTP module remains disabled in the default profile.
Enabling a qualified profile registers six routes below
`/api/v1/projects/{project_id}/knowledge-sync`. Enrollment and synchronization
still require current project membership and the existing database admission.

## Observe and condition requests

`GET /enrollment` can observe the request's actual pinned generation without a
generation header. Its successful response includes the existing enrollment
fields plus a `generation` object:

```json
{
  "contract_version": "1.0.0",
  "descriptor": {
    "profile_id": "memstack-default-v2",
    "generation": 81,
    "digest": "0000000000000000000000000000000000000000000000000000000000000000"
  }
}
```

The values above illustrate the shape. Clients must use the returned values,
including the real digest, rather than constructing a descriptor from settings.
`POST /enrollment` also returns `generation` on success.

Send the observed object as JSON in exactly one
`X-Memstack-Knowledge-Sync-Generation` header for these requests:

| Method | Relative route |
| --- | --- |
| POST | `/enrollment` |
| POST | `/mutations` |
| GET | `/changes` |
| GET | `/conflicts/{conflict_id}` |
| POST | `/conflicts/{conflict_id}/resolve` |

`GET /enrollment` accepts an optional condition and validates it when present.
The header is limited to 2,048 bytes. Both objects require exactly the shown
fields. Duplicate headers, duplicate JSON keys, non-JSON constants, unsupported
versions, Boolean or floating-point generations, and malformed descriptors are
rejected. The generation must be a positive integer; the digest must be 64
lowercase hexadecimal characters; the profile ID must be nonempty without
leading or trailing whitespace.

## Admission and recovery

The Cloud request dependency compares all three descriptor fields against
`current_generation_descriptor_v2()` before authentication or database
dependencies run. Authorization and enrollment admission still run after a
matching condition. Error responses use `detail.code` and a translated
`detail.message`:

| Status | Code | Meaning |
| --- | --- | --- |
| 428 | `knowledge_sync_generation_required` | Observe enrollment and supply a condition. |
| 400 | `knowledge_sync_generation_invalid` | The header or its versioned JSON shape is invalid. |
| 412 | `knowledge_sync_generation_mismatch` | Observe the current generation before another operation. |

Each HTTP request owns a separate generation lease. A generation published
during an admitted request does not replace that request's pin or the descriptor
reported by its enrollment response. A later request using the older descriptor
is rejected before a write. A client must not treat matching descriptors across
requests as a shared lease or automatically retry a write after a mismatch.

The generation condition is not stored in the SQL enrollment record or a durable
link. An enrolled project can continue after a later request observes the new
generation. Disabling the profile removes all six routes, which return 404 even
when an older condition is supplied. Existing mutation, changes, and conflict
response bodies are unchanged.
