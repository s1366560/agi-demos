# Scoped plugin configuration and request replay

The production profile declares each business feature as a separate renderer instance. A
feature owns its routes and aliases, navigation, settings pages, commands and work panels.
Host layouts and the plugin-management recovery entry remain available independently.

## Instance configuration

`GET /api/v1/platform-plugins/v2/instances` accepts `tenant_id` and optional `project_id`.
Reads require membership; updates require the existing tenant or project management authority.
The response includes `scope`, `revision`, `publication` and `instances`. Each instance exposes
its inherited scope, requested enablement, public configuration schema, compatible installed
replacements and effective state. Credentials remain in their existing dedicated management
flows. A manifest must explicitly declare ordinary configuration public and editable before
the instance editor exposes it.

Replacement choices require a distinct installed module with identical targets and contract
digest. The default production bundle currently supplies no alternative editable renderer
implementation, so its replacement selectors have no candidates. Compatibility and atomic
replacement/recovery are covered with admitted test manifests; switching between two actual
production implementations requires installing a second compatible implementation first.

Apply a batch with `POST /api/v1/platform-plugins/v2/instances/apply`:

```json
{
  "tenant_id": "tenant-id",
  "project_id": "project-id",
  "expected_revision": 1,
  "changes": [
    {"entry_id": "builtin-web-feature-tenant-providers", "enabled": false}
  ]
}
```

Use entry IDs returned by the query. An incompatible replacement, invalid schema, unknown
compiled renderer artifact, duplicate contribution or missing dependency rejects the entire
candidate. Source and desired revisions commit together under the existing scope lock.
Concurrent edits receive `instance_revision_conflict`; reload before preparing another batch.

Publication status distinguishes unpublished, reconciling, ready and degraded configurations.
Instance state distinguishes applying, active, disabled and failed. The Web editor also reports
the current browser's renderer result, because server publication readiness alone does not
prove a browser has loaded its candidate. Failed candidates retain the accepted configuration
of the same scope. Changing account, tenant or project revokes the old renderer before loading
the next scope.

Local desktop configuration uses `/api/v1/local-plugins/v2/instances` and `/instances/apply`.
Both instance endpoints require `tenant_id` and `project_id` matching the authenticated current
project. Edits require the current tenant's owner or admin role and affect only that project's
renderer configuration. Local tenant-wide instance editing is not exposed. Sidecar instances
remain read-only in this editor; their installation and lifecycle use their existing dedicated
controls.
Renderer delivery and receipts also accept the current tenant scope without a project; this
does not grant tenant-wide instance editing.
Its accepted renderer receipt is persisted in the existing authority-specific snapshot store.
Saved candidates remain reconciling until the authenticated renderer acknowledges the exact
scope and digest. A failed candidate retains the durable last-good distribution. Business
operation admission reads that accepted configuration; already admitted work keeps its lease.
Signed local WASM installation continues to use its existing signature, permission and vault
controls through the marketplace operation service.

The standalone Rust listener resolves declared feature operations from the same accepted
scope-private publication as Web. In a shared-ledger deployment, a new tenant or project must
first be initialized and published through the existing control plane; a direct Rust request
without that scope's accepted publication returns `feature_configuration_unavailable` (503).
It does not keep reading a parent's changing configuration. Existing Web initialization prepares
this state. Only a successful catalog check proving that all shared publication-ledger tables
are absent permits the bundled defaults in a Rust-only PostgreSQL deployment. Partial schemas,
database errors and invalid accepted bindings fail closed. Replay and running-operation recovery
remain available, while a new WebSocket turn checks the current accepted feature state.

## Typed UI and tool boundaries

Production UI slots use limited contexts and actions for composer, conversation, canvas,
settings and tool results. Actions check scope, generation and draft revision where applicable.
Iframe resources are compiled into the host; an instance nonce and source-window check precede
the `MessageChannel` handshake. Context updates use the resulting port, which closes on unload.
Unknown or failed tool-result display contracts retain the generic result view.

Python and Rust execution paths apply the generation's tool policy before execution, validate
modified arguments and recheck host authority. Policies may continue, deny, request confirmation
or cancel. Final result transforms happen before persistence, UI notification and the next model
input. Read-only after-execution notifications observe that final result. Extension failures
cannot grant permissions that the host did not provide.

## Exact model input

Each provider attempt appends `model_request_prepared` after provider-specific serialization
and before network transport, followed by `model_request_settled`. These records use the existing
session event store. They contain the model-visible JSON, resolved model, attempt identity and
generation context; they do not capture HTTP headers, Authorization or API keys.
Rust waits for the event-store append before transport. Python also reads back the saved
attempt, request body and generation to detect a silently ignored cursor conflict; missing or
modified persistence fails the request before sending it.

An authorized conversation reader can request:

```text
GET /api/v1/agent/conversations/{conversation_id}/messages/{message_id}/model-requests/{attempt_id}?project_id={project_id}
```

The response has `schema_version: 1`, the attempt ID, `status` and `request`. Available requests
include the saved protocol/provider and body. Missing or legacy snapshots return
`status: "snapshot_missing"`, `reason_code: "model_request_snapshot_missing"` and a null request.
This read does not instantiate a plugin generation or rerun completed tools. Retiring plugins
and restarting the application therefore do not recompute historical model input.

Existing installations can update the production baseline with
`scripts/upgrade_root_builtin_bundle_v2.py --upgrade-profile-baseline --all-initialized-scopes`,
along with the script's normal deployment arguments. The upgrade preserves scope-specific
overlays and rejects ambiguous legacy grouped overrides rather than silently discarding them.
