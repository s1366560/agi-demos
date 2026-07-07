# agi-stack I1-I7 Execution Plan

This plan turns the unfinished-function audit into implementation waves. The
rule for every wave is unchanged: exact or method-scoped gateway flips only,
rollback comments, Python wire parity negative controls, server golden coverage,
and the strangler gate from `make strangler-gate`.

## Status

| Iteration | Production status | This checkpoint |
| --- | --- | --- |
| I1 P5 skill evolution loop | Strangler slice complete; runtime gated | Current managed `SKILL.md` content is loaded into the LLM stage engine; auto-apply is available only behind `SKILL_EVOLUTION_AUTO_APPLY=true` and `AGISTACK_SKILL_EVOLUTION_AUTO_APPLY_PRODUCTION_READY=true`; apply/reject/auto-apply outcomes emit Rust-owned audit events, have stale/unsupported action negative controls, and are covered by exact gateway routing plus HTTP rollback e2e. |
| I2 P5 channel active runtime | In progress | Rust now has durable channel outbox lease/claim/finish/fail, a default-off delivery worker with `AUTOSTART` + `PRODUCTION_READY` gates, Feishu webhook delivery adapter, Feishu webhook token/signature verification, public exact-path ingress, webhook idempotency/raw-event plus normalized-event persistence, deterministic session-key projection against `channel_session_bindings`, first-message conversation/binding creation for webhook ingress, live EventStream fanout for newly inserted Feishu webhook message events, local connect/disconnect/health-check status markers, and exact gateway flips with rollback e2e; provider credential rotation, live provider sessions, and full session/workspace message routing remain future. |
| I3 P6 workspace runtime | In progress | Mention runtime remains default-off and production-gated; runtime response payloads now include deterministic token chunks, the response-ready handoff persists chunk-level blackboard stream events before the final workspace message, persisted chunk delivery enforces bounded stream backpressure, the handler fans out the same token/message events to a workspace `EventStream` topic, and the Rust WS bridge now supports workspace-scope/member-authorized stream subscription/replay without trusting client-supplied project ids alone; SessionProcessor/tool/HITL runtime remain future. |
| I4 P3/F11 agent runtime | Partial foundation | Worker launch now emits a Rust control-plane admission snapshot (`admit`, duplicate cooldown skip, already-running skip) into task metadata while preserving the existing Python-owned executor boundary; SubAgent template category discovery now has an exact Rust read slice over Python-owned `subagent_templates`; builtin slash-command catalog discovery now has an exact Rust read slice preserving Python's 23-command registry and filters; full worker process ownership, command execution, tool/HITL execution and backpressure remain future. |
| I5 P4 graph/search completion | Partial foundation | Project-scoped graph REST/search foundation exists; `background=true` community rebuild now persists a Rust-owned requested/started/completed job record to the shared EventStream, runs the projection in a background worker task, and exposes an exact Rust job-status endpoint, rebuilds persist stable `Community` nodes plus `HAS_MEMBER` edges without feeding them back into Louvain detection, stale persisted `Community`/`HAS_MEMBER` artifacts are pruned on rebuild through project-scoped `GraphStore` deletes, episode ingest now best-effort projects `Episodic` graph nodes and LLM-extracted `Memory.entities` as stable `Entity` nodes plus `MENTIONS` edges without changing the already flipped P1 response contract, optional LLM relationship extraction now projects stable entity-to-entity graph edges only when both `AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_ENABLED=true` and `AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_PRODUCTION_READY=true` are set, query-style enhanced search can fan out over the current user's accessible projects when `project_id` is omitted, community enhanced search can resolve omitted `project_id` by scanning identity-visible projects for the stable community handle, traversal enhanced search can resolve omitted `project_id` by scanning identity-visible projects for the start entity, project-scoped graph snapshot export/import now has exact Rust routes plus gateway rollback coverage, and the already-flipped enhanced-search capabilities discovery route now has server golden plus proxy rollback e2e coverage. LLM reflexion remains future. |
| I6 P7 long-tail domains | Partial foundation | The genes/instances group now has exact Rust `GET /api/v1/genes/`, `GET /api/v1/genes/:gene_id`, `GET /api/v1/genes/genomes`, `GET /api/v1/genes/genomes/:genome_id`, `GET /api/v1/instances/`, `GET /api/v1/instances/:instance_id`, `GET/PUT /api/v1/instances/:instance_id/config`, `PUT /api/v1/instances/:instance_id/config/pending`, `GET/PUT /api/v1/instances/:instance_id/llm-config`, `GET /api/v1/instances/:instance_id/members`, `POST /api/v1/instances/:instance_id/members`, `GET /api/v1/instances/:instance_id/members/search-users`, `PUT /api/v1/instances/:instance_id/members/:member_id`, `DELETE /api/v1/instances/:instance_id/members/:user_id`, and `GET /api/v1/instances/:instance_id/channels` over Python-owned `gene_market`, `genomes`, `instances`, `instance_members`, and `instance_channel_configs`; gene/genome writes/install/reviews/ratings/evolution plus instance writes/runtime/config apply/files/channel mutations-tests remain Python-owned. The observability/audit/events/DLQ group now has typed agent-event replay filtering (`event_types=error,dead_letter`) on the already flipped replay endpoint, exact Rust `GET /api/v1/events` list and `GET /api/v1/events/types` discovery over Python-owned `tenant_event_logs`, tenant-scoped exact Rust audit list/filter/runtime-hook list/summary/export reads over Python-owned `audit_logs`, and exact Rust admin DLQ list/detail/stats/retry/discard/cleanup over Python-owned Redis DLQ keys with Postgres admin access parity plus `UnifiedEventBus` Redis Stream republish parity; event writes remain Python-owned. The notifications/webhooks group has exact Rust `GET /api/v1/notifications/`, `PUT /api/v1/notifications/:notification_id/read`, `PUT /api/v1/notifications/read-all`, `DELETE /api/v1/notifications/:notification_id`, and `POST /api/v1/notifications/create` over Python-owned `notifications` plus method-scoped Rust `GET/POST/PUT/DELETE /api/v1/tenant-webhooks/:id` CRUD over Python-owned `webhooks`, while webhook provider delivery remains Python-owned. The billing/support/export group has exact Rust `GET /api/v1/tenants/:tenant_id/billing`, `GET /api/v1/tenants/:tenant_id/invoices`, `POST /api/v1/tenants/:tenant_id/upgrade`, API-v1 `GET/POST /api/v1/support/tickets`, `GET/PUT /api/v1/support/tickets/:ticket_id`, `POST /api/v1/support/tickets/:ticket_id/close`, the same legacy `/support/tickets` compatibility routes over Python-owned `tenants/projects/memories/user_projects/invoices` / `support_tickets`, exact Rust `GET /api/v1/data/stats`, exact Rust `POST /api/v1/data/export`, and exact Rust `POST /api/v1/data/cleanup` over the portable GraphStore stats/export/cleanup contracts with Python-compatible scope resolution and cleanup admin gates; other support/data siblings remain Python-owned. The LLM providers/deploy/cron/maintenance group now has exact Rust `GET/POST /api/v1/llm-providers/`, no-slash collection parity, `GET/PUT/DELETE /api/v1/llm-providers/:provider_id` metadata CRUD with Python-compatible API-key encryption/masking, `GET /api/v1/llm-providers/types` static provider discovery, admin-only `GET /api/v1/llm-providers/env-detection`, read-only `GET /api/v1/llm-providers/models/catalog`, `GET /api/v1/llm-providers/models/catalog/search`, `GET /api/v1/llm-providers/models/:provider_type` over Python's embedded `models_snapshot.json`, `GET /api/v1/llm-providers/:provider_id/health` over Python-owned `provider_health`, `GET /api/v1/llm-providers/tenants/:tenant_id/assignments` over Python-owned `tenant_provider_mappings`, `GET /api/v1/llm-providers/:provider_id/usage` over Python-owned `llm_usage_logs`, graph/retrieval-store type/list/detail plus metadata create/update/delete over Python-owned store tables, project cron job list/detail/run-history reads over Python-owned `cron_jobs` and `cron_job_runs`, deploy list/detail/latest reads over Python-owned `instances` and `deploy_records`, and exact Rust `GET /api/v1/maintenance/status` over the portable GraphStore stats/count ports; model catalog refresh, active provider health checks/writes, tenant assignment mutations/provider resolution, system resilience runtime/reset, graph/retrieval-store live connection test routes, cron writes/runtime, deploy writes/lifecycle/progress, and maintenance refresh/optimization/invalidation mutations remain Python-owned. The schema/artifacts/uploads group has exact Rust project schema collection reads plus method-scoped schema create/update/delete over Python-owned `entity_types`, `edge_types`, and `edge_type_maps`, exact Rust artifact list/detail/category-list reads plus `PUT /api/v1/artifacts/:artifact_id/content` save-back and `DELETE /api/v1/artifacts/:artifact_id` soft-delete over Python-owned `artifacts` and the shared ObjectStore, and exact Rust attachment list/detail reads plus `POST /api/v1/attachments/upload/simple` simple upload and `DELETE /api/v1/attachments/:attachment_id` hard-delete over Python-owned `attachments` and the shared ObjectStore; artifact download/refresh/upload/multipart lifecycle, attachment multipart upload/download, and broader uploads remain Python-owned. Delivered groups have Postgres/Redis adapter coverage where shared state is involved, golden response shapes, and gateway rollback e2e; remaining long-tail groups are future. |
| I7 platform release hardening | Partial foundation | Existing multi-platform build evidence is not enough for launch claims; go/no-go bench scorecard now runs in CI, restores the previous approved baseline, persists a JSON scorecard artifact, fails on historical baseline regressions, and publishes a Markdown trend summary; WASM now exposes a persistence snapshot API plus an IndexedDB JS host store/facade that can auto-save after ingest and restore after reload, desktop bundle creation has a dedicated Make target plus macOS CI artifact job and static bundle smoke check, Android/iOS unsigned mobile artifacts now have CI jobs, the scorecard records UniFFI mobile binding ingest/search/semantic-search latency through the real `MobileCore` SQLite surface, and the public runtime engine catalog plus authenticated system metadata now have exact Rust slices. Host-store smoke now covers deterministic IndexedDB missing-store upgrade/open-failure cases plus real Chrome IndexedDB reload, missing-store upgrade, and CDP offline persistence; updater metadata/entitlements, install/launch smoke, signed distribution, sandbox engine execution, and runtime maintenance mutations remain required. |

## Shared Delivery Contract

1. Each route flip must add or update a server golden, gateway HTTP/WS e2e, route rollback test, and Python negative control.
2. Gateway changes must be exact paths or `MethodRule`s. Do not flip broad siblings such as `/api/v1/*`.
3. Every production runtime path needs an explicit readiness gate named `*_PRODUCTION_READY` or an equivalent narrower gate.
4. Core crates stay runtime-agnostic. `tokio`, `tonic`, `sqlx`, Redis, Neo4j, and LLM HTTP clients remain server/adapters-only.
5. Runtime workers must prove single-owner claim idempotency, crash retry, replay, backpressure, and HITL resume before draining production queues.

## I1 P5 Skill Evolution Loop

Goal: close the managed-skill loop without silently mutating production skills.

Delivered in this checkpoint:

- Pipeline evidence now carries current managed skill content when a tenant or project skill exists, preferring the `skill_versions` row for `skills.current_version` and falling back to `skills.full_content` only when the current version is absent or blank.
- The LLM evolve prompt includes the current `SKILL.md` content instead of evolving from a blank placeholder.
- Production composition uses a composite Postgres-backed pipeline store that can apply reviewed jobs through the managed skill repository.
- Auto-apply requires both `SKILL_EVOLUTION_AUTO_APPLY=true` and `AGISTACK_SKILL_EVOLUTION_AUTO_APPLY_PRODUCTION_READY=true`; otherwise jobs remain `pending_review`.
- Added Rust-owned additive `agistack_skill_evolution_job_audit_events` for apply, reject, and auto-apply review outcomes without changing Python-owned skill tables.
- Review apply/reject paths now record actor, job id, version id or rejected candidate id, and structured details for audit replay.
- Auto-apply records the applied version id and run id after the reviewed job transitions to `applied`.
- Added negative controls for unsupported pending job actions and stale reviewed jobs that are no longer `pending_review`.
- Gateway routing now uses exact/method-scoped skill-evolution rules for config, overview, run admission, apply/reject, and per-skill evolution detail/run paths without claiming unknown siblings.
- Gateway HTTP e2e now proves representative skill-evolution paths route to Rust while cancel, extra child paths, and wrong-method siblings remain Python-routable for rollback.

Remaining:

- No additional gateway flip is pending for the current managed-skill loop. Future expansion must add a new exact rule and rollback/e2e before claiming any new skill-evolution sibling.

Acceptance evidence:

- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server dev_service_applies_and_rejects_evolution_jobs -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server skill_evolution_pipeline_executor_auto_applies_only_when_gate_is_ready -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres --test pg_integration skill_evolution_overview_queries_shared_schema -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres skill_evolution_job_audit_events_roundtrip -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough -- --nocapture`
- Golden covering pending-review, applied, rejected, and gate-blocked states.

## I2 P5 Channel Active Runtime

Goal: move from Rust read-only channel foundation to owned runtime write paths.

Delivered in this checkpoint:

- Added Rust-owned additive `agistack_channel_outbox_leases` for delivery ownership without altering Python-owned `channel_outbox`.
- Added Postgres adapter operations to claim due outbox rows with `FOR UPDATE SKIP LOCKED`, prevent duplicate active delivery via owner leases, mark rows `sent`, and mark failures as retryable `failed` or terminal `dead_letter`.
- Added live-gated Postgres integration coverage for owner-only completion, active lease duplicate prevention, retry delay blocking, re-claim after retry time, and dead-letter transition.
- Added Rust-owned additive `agistack_channel_webhook_events` for webhook idempotency and raw event/header persistence without altering Python-owned channel tables.
- Added Postgres adapter operation to resolve webhook events through `channel_configs`, persist project/channel metadata, return duplicate status for existing idempotency keys, and avoid treating missing config as a storage failure.
- Added live-gated Postgres integration coverage for config resolution, duplicate preservation of the first raw event, and missing-config handling.
- Added a secret-bearing webhook credential projection (`verification_token`, `encrypt_key`) that is separate from public channel config views and covered by live-gated Postgres integration.
- Added a Feishu webhook verifier matching the Python token extraction paths (`header.token`, `event.header.token`, top-level `token`) and Lark/Feishu SHA-256 signature contract (`timestamp + nonce + encrypt_key + raw_body`).
- Added public exact-path Rust ingress at `POST /api/v1/channels/configs/:config_id/webhook/feishu`; it returns URL verification challenges or persists verified raw events with stable idempotency keys, while leaving Agent/workspace execution unclaimed.
- Added additive `normalized_event_json` persistence on Rust-owned webhook events. Feishu message callbacks now project provider, schema version, idempotency key, event id/type, message id, chat id/type, thread id, topic id, and sender open id; duplicate replays return the first persisted normalized projection instead of rewriting event meaning.
- Added additive route projection fields (`route_session_key`, `route_binding_id`, `route_conversation_id`) on Rust-owned webhook events. Rust now builds the same deterministic session key shape as Python (`project:{project}:channel:{channel}:config:{config}:{dm|group}:{chat}` plus optional topic/thread), resolves existing `channel_session_bindings`, marks events `routed` or `unbound`, and keeps missing/unsupported routing errors observable without creating new conversations.
- Added webhook-owned first-message session creation. When Feishu ingress resolves a valid session key with no existing binding, Rust now creates a Python-shaped `conversations` row and a unique `channel_session_bindings` row in the same Postgres transaction, using the project owner or channel config creator as the effective user, Python-compatible conversation metadata, and the same title shape (`Feishu: Group Chat` / `Feishu: Chat with ...`).
- The new session-creation transaction is race-safe: a concurrent creator that wins the `(project_id, session_key)` binding race is reused, and the losing transaction removes its unused generated conversation before routing the event to the existing binding.
- Added server unit coverage for the create-record metadata/title projection and live-gated Postgres integration coverage for unbound webhook routing creating the conversation/binding, routing subsequent messages to the same conversation, and avoiding orphan conversations.
- Feishu webhook ingress now publishes newly inserted normalized events to `channel:events:{project_id}` with a stable `channel:{config_id}:{idempotency_key}` routing key, route projection fields, and response `routed_event_id`; duplicate idempotency replays do not emit another live event.
- Added server golden coverage for webhook challenge and ingress response shapes.
- Added a server-only channel outbox delivery runtime foundation: it claims due outbox rows, builds provider delivery requests with `content_text`, records sent provider message ids, records retryable provider failures, and reports lost leases without double-counting delivery.
- Extended the Postgres channel outbox projection to include `project_id` and `content_text`, matching the existing Python-shaped `channel_outbox` table and enabling provider payload construction.
- Extended channel outbox claims with `channel_type`, `webhook_url`, and `domain` from enabled channel configs so provider adapters do not need a second config lookup after ownership is claimed.
- Added a Feishu/Lark webhook deliverer that posts text-message payloads to the configured webhook URL, treats provider message ids as sent ids when returned, maps HTTP/provider failures to retryable delivery failures, and honors numeric `Retry-After` backoff.
- Wired a default-off channel outbox delivery worker into server composition. It only autostarts when both `AGISTACK_CHANNEL_OUTBOX_DELIVERY_AUTOSTART=true` and `AGISTACK_CHANNEL_OUTBOX_DELIVERY_PRODUCTION_READY=true` are set, and leaves the queue untouched when either gate is closed.
- Added authenticated local lifecycle endpoints for `POST /api/v1/channels/configs/:config_id/connect`, `disconnect`, and `health-check`. These update shared config status markers only: disabled configs cannot connect, disconnect clears local status, and health-check projects enabled configs as connected while disabled configs return a local error marker.
- Added exact gateway rules for Feishu webhook ingress and the three local lifecycle endpoints, with routing unit coverage and HTTP proxy e2e proving wrong method, wrong provider, extra child paths, and other config runtime actions remain Python-routable rollback boundaries.

Sequence:

1. Webhook ingress: exact Feishu webhook gateway flip, provider-specific normalization, replay-safe idempotency, first-message conversation/binding creation, and route projection are delivered; next step is runtime handoff before any additional provider or sibling route is flipped.
2. Outbox delivery: add credential rotation and live provider rate-limit integration on top of the delivered gated Feishu/Lark webhook adapter foundation.
3. Message routing: Feishu inbound normalized-event live fanout plus session-binding creation/projection are delivered; next step is handing routed messages to workspace/chat runtime and outbound response routing.
4. Connection lifecycle: local connect/disconnect/health-check status markers are delivered; next step is live provider session checks and credential refresh semantics.
5. Gateway flip: add one method-scoped rule per stable runtime endpoint after golden and rollback tests pass.

Acceptance evidence:

- Live-gated provider adapter tests skip when credentials are absent but must run in CI integration jobs.
- Redis/Postgres unavailable tests prove no message loss claim is made.
- Gateway still routes unimplemented channel siblings to Python.
- `cargo test -p agistack-adapters-postgres channel`
- `cargo test -p agistack-server channel_api`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server channel_api::delivery_runtime -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres channel_connection_lifecycle_updates_shared_config_status -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres channel_webhook_route_projection_matches_existing_session_binding -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres channel_webhook_route_creates_session_binding_and_conversation_when_unbound -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway p5_channel_config_rules_are_exact -- --nocapture`
- Feishu webhook adapter local HTTP tests cover success payload shape, provider `Retry-After` retry mapping, and gated worker lifecycle/no-claim safety.
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server channel_webhook_event_payload_routes_normalized_message_to_project_stream -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server channel_webhook_session_create_record_matches_python_conversation_shape -- --nocapture`
- `make -C agi-stack strangler-gate`

## I3 P6 Workspace Runtime

Goal: turn parked `runtime_bound` mention/outbox state into production delivery without broad endpoint takeover.

Sequence:

1. Keep `AGISTACK_WORKSPACE_MENTION_RUNTIME_ENABLED=false` by default and require a production-ready gate for LLM writer activation.
2. Delivered foundation: runtime `response_ready` payloads carry `runtime_token_chunks` plus `runtime_stream_delivery=final_content_chunks`, giving the future streaming producer a stable downstream payload contract.
3. Delivered foundation: the response-ready handler persists one `workspace_agent_mention_token_chunk` blackboard outbox event per runtime chunk, then persists the final `workspace_message_created` event with chunk delivery metadata.
4. Delivered foundation: persisted runtime chunk delivery is bounded to 128 chunks / 64K chars per response. When a runtime payload exceeds the bound, the final workspace message still persists the full final content, but the chunk stream is marked `runtime_stream_backpressure=truncated`, includes original count/char diagnostics, and does not mark the last persisted chunk as stream-final.
5. Delivered foundation: the response-ready handler now appends token chunk events and the final workspace message event to `workspace:events:{workspace_id}` after durable blackboard persistence. The append is best-effort for live delivery, while the durable blackboard outbox remains the source of recovery.
6. Delivered foundation: the Rust WS bridge now accepts `subscribe_workspace` / `unsubscribe_workspace`, resolves the target workspace's tenant/project scope, verifies optional tenant id matches the workspace, requires workspace read membership before subscribing, replays from `last_event_id`, and forwards workspace token/message events with stable `event_id` plus `workspace:{workspace_id}` routing keys.
7. Complete `SessionProcessor`, tool, HITL, and agent-chain completion integration.
8. Prove multi-worker outbox claim idempotency, retry ownership, stale recovery, and crash replay.
9. Flip additional workspace runtime endpoints only after replay/backpressure tests pass.

Acceptance evidence:

- Worker crash/retry tests.
- Redis/EventStream replay tests.
- HITL resume tests.
- Persisted stream backpressure tests; live fan-out backpressure remains future.
- Multi-worker claim idempotency tests.
- `cargo test -p agistack-server agent_mention_runtime`
- `cargo test -p agistack-server workspace_mention_runtime`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server workspace_outbox_worker::tests::agent_mention_runtime -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server workspace_outbox_worker_fans_out_runtime_chunks_to_event_stream -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server agent_ws::subscriptions -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server dev_service_authorizes_workspace_event_subscription_by_workspace_scope -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres workspace_repository_roundtrips_against_shared_schema -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)

## I4 P3/F11 Agent Runtime

Goal: replace the Ray executor with a Rust worker/control-plane runtime.

Delivered in this checkpoint:

- Worker launch admission is now centralized into a Rust control-plane snapshot.
- The snapshot records whether the worker launch was admitted, skipped because a reused conversation is already running, or skipped because a duplicate cooldown lease is active.
- Admitted launches persist `worker_runtime_admission` metadata with the control-plane name, conversation id, reuse/stream-poll flags and cooldown claim outcome.
- This preserves the current no-Python-executor-coexistence constraint by not pretending Rust owns actual worker process execution before the F11 harness exists.
- Added exact Rust `GET /api/v1/subagents/templates/categories` for SubAgent template marketplace category discovery. It preserves Python's tenant-scoped, published-only, distinct category ordering over `subagent_templates`, while template list/create/detail/install and runtime SubAgent siblings remain Python-owned with rollback coverage.
- Added exact Rust `GET /api/v1/agent/commands` for builtin slash-command catalog discovery. It preserves Python's 23-command registry, aliases, argument metadata, category filters, and scope matching semantics, while command execution plus agent tools/workflows/conversation/message siblings remain Python-owned with rollback coverage.

Architecture:

- Control plane: worker registry, lease ownership, session actor lifecycle, health, placement, and crash recovery.
- Data plane: gRPC/tokio worker protocol, tool execution, HITL suspension/resume, event stream delivery, and backpressure.
- Supervision: retry budget, doom-loop verdict tool-call, terminal outcome projection, and durable recovery records.

Sequence:

1. Define server-only worker/control-plane APIs and keep core runtime-agnostic.
2. Build a single-process worker harness and golden event stream.
3. Add multi-worker lease ownership with crash retry.
4. Add tool/HITL runtime execution and resume.
5. Move workspace worker runtime to this foundation, then expand gateway flips.

Acceptance evidence:

- Worker crash/retry ownership.
- Event replay and stream backpressure.
- HITL resume and timeout behavior.
- No Python executor coexistence on flipped paths.

## I5 P4 Graph/Search Completion

Goal: finish graph/search parity without breaking existing project-scoped contracts.

Sequence:

Delivered in this checkpoint:

- `POST /api/v1/graph/communities/rebuild?background=true` no longer returns Rust 501 or performs a request-time projection. It returns an accepted job envelope, appends a `graph_community_rebuild_requested` record to `graph:community_rebuilds:{project_id}`, and runs the projection in a spawned Rust worker task.
- The background worker appends `graph_community_rebuild_started` and `graph_community_rebuild_completed` records with stable job id, status, project id, processed entity count, and community count. Worker failures append `graph_community_rebuild_failed` instead of silently dropping ownership.
- Added exact `GET /api/v1/graph/communities/rebuild/jobs/:job_id?project_id=...` job status lookup. It reads the project EventStream topic, filters by job id, returns the latest status plus the bounded event sequence, and 404s when the requested job is no longer retained or never existed.
- Added server golden coverage for the queued background response plus regression coverage proving requested/started/completed EventStream records are persisted for the same job id.
- Added server golden coverage for the completed job-status response and exact gateway rollback coverage for the status route.
- Community rebuild now persists stable `Community` graph entities and `HAS_MEMBER` relationships back through the portable `GraphStore` port, so in-memory/device/Neo4j tiers share the same persistence surface.
- Persisted community artifacts are filtered out of subsequent Louvain inputs, preventing rebuilds from counting synthetic `Community` nodes or `HAS_MEMBER` edges as source graph data.
- Added project-scoped `GraphStore` delete operations across in-memory, SQLite, and Neo4j tiers. Deleting an entity also removes same-project touching relationships, preventing stale graph snapshots from returning dangling edges.
- Community rebuild prunes stale persisted `Community` nodes and obsolete `HAS_MEMBER` edges before upserting the current projection, so disappeared or changed communities converge instead of accumulating synthetic artifacts.
- Added regression coverage proving a second rebuild keeps community counts and processed source-entity counts stable after Community nodes have been persisted, and proving stale community artifacts are removed when a source community disappears.
- `POST /api/v1/episodes` now best-effort upserts an `Episodic` graph node keyed by the returned memory/episode id after the existing memory ingest succeeds. Graph projection failures do not change the already flipped P1 response/error contract.
- The same best-effort graph projection now reuses the already-required LLM memory extraction result: `Memory.entities` are projected as stable project-scoped `Entity` nodes and deduplicated `Episodic -MENTIONS-> Entity` relationships through the portable `GraphStore` port.
- The graph projection now has an optional LLM relationship pass over already-extracted memory entities. It is default-off and requires both `AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_ENABLED=true` and `AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_PRODUCTION_READY=true`; when enabled, the HTTP LLM adapter asks for structured `relationships[]`, maps source/target names back to the project-scoped projected entities, sanitizes relationship types structurally for graph adapters, clamps scores, skips unknown/self endpoints, and writes stable entity-to-entity `Relationship` edges through the portable `GraphStore`.
- Added regression coverage proving episode ingest persists the `Episodic` node in the project graph while preserving the existing episode response golden.
- Added regression coverage proving extracted entity projection writes stable entity nodes and deduplicated mention edges without changing the existing episode response golden.
- Added regression coverage proving the relationship extraction gate is closed unless both env flags are set, relation types are normalized to graph-adapter-safe tokens, unknown endpoints are ignored, and scores are clamped before relationship edge projection.
- Query-style enhanced search endpoints (`advanced`, `temporal`, `faceted`, and `memory/search`) now preserve explicit `project_id` behavior and fan out through `IdentityService::list_projects` when `project_id` is omitted.
- Fan-out responses expose `scope.project_ids` and `filters_applied.project_ids`; fan-out result metadata carries the source `project_id`.
- Added golden coverage proving fan-out only searches the identity-visible project list and does not leak graph entities from another project stored in the same graph adapter.
- Community enhanced search now preserves explicit `project_id` behavior and resolves omitted `project_id` by searching only identity-visible projects for the requested stable community id. Fan-out community results expose source `project_id` in result metadata plus response scope, while inaccessible projects remain excluded.
- Added golden coverage for community fan-out membership scoping.
- Graph traversal enhanced search now preserves explicit `project_id` behavior and resolves omitted `project_id` by searching only identity-visible projects for the start entity. Fan-out traversal results expose source `project_id` in result metadata plus response scope, while inaccessible project graphs remain excluded.
- Added golden coverage for traversal fan-out start-entity membership scoping.
- Added project-scoped graph snapshot export/import at exact Rust paths: `GET /api/v1/graph/export` emits a versioned package with entities, relationships, counts, and export timestamp; `POST /api/v1/graph/import` validates version, project scope, and bounded counts before upserting through the GraphStore port.
- Added server golden coverage for graph export snapshots, import roundtrip coverage, cross-project import negative control, and exact gateway rollback e2e for export/import without claiming broader graph migration siblings.
- Added server golden coverage and gateway HTTP proxy rollback coverage for the already-flipped `GET /api/v1/search-enhanced/capabilities` discovery route, including a wrong-method negative control.
- Added exact Rust graph-store metadata slice: `GET /api/v1/graph-stores/types`, collection `GET/POST /api/v1/graph-stores`, and item `GET/PUT/DELETE /api/v1/graph-stores/:store_id`. It preserves Python's Neo4j/ArcadeDB/Apache AGE type metadata, default env store projection, default/explicit tenant access selection, admin-only write gate, Python AES-256-GCM shared-row config encryption/decryption, top-level secret masking, name-conflict `409`, env-store read-only `400`, bound-project delete protection, soft-delete, and created/updated timestamp shape over Python-owned `graph_stores`; live connection test routes remain Python-owned with rollback coverage.
- Added exact Rust retrieval-store metadata slice: `GET /api/v1/retrieval-stores/types`, collection `GET/POST /api/v1/retrieval-stores`, and item `GET/PUT/DELETE /api/v1/retrieval-stores/:store_id`. It preserves Python's MemStack pgvector, WeKnora remote, and planned vector-backend type metadata, default env store projection, default/explicit tenant access selection, admin-only write gate, Python AES-256-GCM shared-row config encryption/decryption, top-level secret masking including `authorization`, retrieval required-field validation including WeKnora knowledge-base requirements, name-conflict `409`, env-store read-only `400`, bound-project delete protection, soft-delete, and created/updated timestamp shape over Python-owned `retrieval_stores`; live connection test routes remain Python-owned with rollback coverage.
- Added exact Rust `GET /api/v1/sandbox/profiles` for authenticated legacy sandbox profile discovery. It preserves Python's Lite/Standard/Full profile order and resource metadata, while legacy sandbox lifecycle, create, tools, services, and event siblings remain Python-owned with rollback coverage.

Sequence:

1. Durable EventStream-backed background rebuild job persistence, worker execution, and exact public job status lookup are delivered for project-scoped community projections.
2. Community fan-out is delivered for stable community ids; traversal fan-out is delivered by resolving the start entity over identity-visible projects and then traversing exactly one matching project graph.
3. Persisted `Community` nodes, `HAS_MEMBER` edges, stale community pruning, and best-effort `Episodic` nodes are delivered through the existing graph store; any dedicated schema migration remains future.
4. LLM-extracted entity and mention-edge projection is delivered by reusing the existing `MemoryService::ingest_episode` extraction result. Relationship extraction is delivered as a gated optional enrichment pass; reflexion remains future and must land behind readiness gates.
5. Expand enhanced search fan-out to persisted Community/Episodic nodes.

Acceptance evidence:

- Migration/export/import roundtrip.
- Project-scoped endpoint backward compatibility.
- `cargo test -p agistack-server graph_api`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server graph_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server rebuild_communities_background_persists_job_events_and_worker_completion -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server rebuild_communities_job_status_matches_golden -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server rebuild_communities_persists_community_nodes_without_polluting_detection -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server rebuild_communities_prunes_stale_persisted_community_artifacts -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-mem graph::tests -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-device graph::tests -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-neo4j neo4j_matches_in_memory_across_all_reads -- --nocapture` (live-gated; skips when Neo4j is unavailable)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server create_episode_persists_episodic_graph_node -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server episode_graph_projection_persists_extracted_entities_and_mentions_edges -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server prod_api::unit -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-http-llm parse_relationship_drafts_accepts_wrapped_and_defaults_optional_fields -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server enhanced_search -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server capabilities_and_error_envelopes_are_fastapi_compatible -- --nocapture`
- Tenant fan-out golden and negative membership controls.
- Community fan-out golden and identity-membership controls.
- Traversal fan-out golden and identity-membership controls.
- LLM extraction tests are live-gated and skip cleanly without LLM config.

## I6 P7 Long-Tail Domains

Goal: migrate long-tail API groups in bounded batches.

Delivered in this checkpoint:

- Added exact Rust `GET /api/v1/auth/me` and `GET /api/v1/users/me` current-user reads over the Python-owned `users`, `user_roles`, and `roles` tables. The response preserves Python's `User` schema, persisted profile object, preferred language, sorted role names, and authenticated-user 404 behavior while `PUT /api/v1/users/me`, force-change-password, API key management, and other `/auth/*` siblings remain Python-owned.
- Extended `GET /api/v1/agent/conversations/:conversation_id/events` with backward-compatible `event_types` filtering.
- The filter is structural and bounded: comma-separated event type names, deduped, max 20 values, max 80 characters each, ASCII protocol characters only.
- Postgres replay uses a bound `text[]` filter with empty-array default semantics; no SQL string concatenation is introduced.
- Dev replay applies the same validated filter to in-process `EventStream` payloads.
- Added golden coverage for filtered `error` + `dead_letter` replay response shape and live-gated Postgres integration coverage.
- Added exact Rust `GET /api/v1/events` and `GET /api/v1/events/types` for tenant event log listing and event type discovery. They preserve Python's default tenant selection by using the oldest user membership, validate explicit tenant scope through the identity service, and read from Python-owned `tenant_event_logs`.
- Event list queries preserve Python's `event_type`, `date_from`, `date_to`, `page`, and `page_size` contract with bound Postgres parameters, total count, `created_at DESC, id ASC` ordering, and the `items/total/page/page_size` response shape.
- Added server golden coverage for the Python list response and `list[str]` type response shapes, live-gated Postgres adapter coverage for distinct/sorted/tenant-scoped event types plus filtered counted list pagination, and gateway unit/e2e rollback controls proving filters, exports, extra children, and write methods remain Python-owned.
- Added exact Rust tenant audit reads for `GET /api/v1/tenants/:tenant_id/audit-logs`, `/filter`, `/runtime-hooks`, and `/runtime-hooks/summary`. They preserve Python's tenant-exists-first access gate, global admin bypass (`users.is_superuser` / `system_admin` role), any-role tenant membership access, legacy `tenant_id IS NULL` audit-row inclusion, limit/offset bounds, timestamp filtering, runtime-hook detail filters, `timestamp DESC, id ASC` ordering, and list/summary response shapes over Python-owned `audit_logs`.
- Added exact Rust `GET /api/v1/tenants/:tenant_id/audit-logs/export` over Python-owned `audit_logs`. It preserves Python's tenant access gate, CSV default, JSON export option, runtime-hook export auto-detection from hook filters or `runtime_hook.*` action, 10,000-row export cap, Python-style sorted `details` JSON string, CSV quoting/CRLF dialect, and `Content-Disposition` attachment filename.
- POST/write-side logging and extra children remain Python-owned with gateway rollback coverage.
- Added server golden coverage for audit list and runtime-hook summary response shapes plus live-gated Postgres adapter coverage for tenant access helpers, filtered audit listing, runtime-hook detail filters, summary counts, and legacy system-row inclusion.
- Added exact Rust admin DLQ reads for `GET /api/v1/admin/dlq/messages`, `GET /api/v1/admin/dlq/messages/:message_id`, and `GET /api/v1/admin/dlq/stats` over Python-owned Redis DLQ keys.
- Admin DLQ reads preserve Python's global admin gate (`users.is_superuser` or legacy `admin|system_admin|super_admin` role), invalid status `400` detail, pending/error/event sorted-set selection precedence, routing-key wildcard filtering, Redis stats hash projection, and message response fields including `can_retry` and `age_seconds`.
- Added exact Rust admin DLQ mutations for `DELETE /api/v1/admin/dlq/messages/:message_id`, `POST /api/v1/admin/dlq/messages/:message_id/retry`, `POST /api/v1/admin/dlq/messages/retry`, `POST /api/v1/admin/dlq/messages/discard`, `POST /api/v1/admin/dlq/cleanup/expired`, and `POST /api/v1/admin/dlq/cleanup/resolved`. They preserve Python's Redis message update/index removal/stat-counter side effects for retry, discard, and cleanup.
- DLQ retry now republishes the stored `EventEnvelope` to the Python-compatible `events:{routing_key}` Redis Stream with `event_id`, `event_type`, `schema_version`, `data`, `timestamp`, `routing_key`, and optional correlation/causation fields. Single retry returns Python's `Retry initiated`/`Retry failed` shape; bulk retry preserves Python's per-message false results for missing or non-retryable messages.
- Added server golden coverage for DLQ list/stats/retry/bulk-retry/discard/cleanup response shapes, live-gated Redis adapter coverage for Python DLQ keys/filter precedence/stats/retry Stream republish/discard/cleanup side effects, and live-gated Postgres adapter coverage for admin access projection.
- Added exact trailing-slash Rust `GET /api/v1/notifications/` for current-user notification listing. It preserves Python's `unread_only` default, `limit` bounds, SQL-limit-before-expiration-filtering behavior, created-desc ordering, current-user scoping, and response shape over Python-owned `notifications`.
- Added exact/method-scoped Rust `PUT /api/v1/notifications/:notification_id/read`, `PUT /api/v1/notifications/read-all`, `DELETE /api/v1/notifications/:notification_id`, and `POST /api/v1/notifications/create` for current-user notification mutations over Python-owned `notifications`. They preserve Python's current-user ownership gates, `Notification not found` 404, read-all count projection, create defaults (`type=general`, `title=Notification`, `message=""`, `data={}`), `expires_at` ISO/Z timestamp parsing with invalid timestamp 400, and superuser-only create-for-other-user behavior.
- No-slash collection `GET /api/v1/notifications`, wrong methods, reserved children, and unknown mutation siblings stay Python-owned with gateway rollback coverage.
- Added server golden coverage for notification list/success/read-all/create response shapes and live-gated Postgres adapter coverage for current-user scoping, unread filtering, ordering/limit behavior, mutation ownership, create persistence, and superuser projection.
- Added method-scoped Rust tenant webhook CRUD: `GET /api/v1/tenant-webhooks/:tenant_id`, `POST /api/v1/tenant-webhooks/:tenant_id`, `PUT /api/v1/tenant-webhooks/:webhook_id`, and `DELETE /api/v1/tenant-webhooks/:webhook_id`. It preserves Python's tenant-exists-first admin gate, global admin bypass (`users.is_superuser` / `system_admin` role), tenant `admin|owner` access, denial details (`Tenant access required` / `Admin access required`), create-only secret return (`whsec_` + 64 lowercase hex chars), list/update secret redaction, 204 delete success, `Webhook not found` 404s, `deleted_at IS NULL` filtering, and `created_at DESC` ordering over Python-owned `webhooks`.
- Webhook provider delivery remains Python-owned with gateway rollback coverage.
- Added server golden coverage for tenant webhook list/create/update response shapes and live-gated Postgres adapter coverage for tenant admin role projection, global admin projection, create/update/delete behavior, deleted-row filtering, event array projection, and created-desc ordering.
- Added exact Rust `GET /api/v1/tenants/:tenant_id/invoices` for billing invoice listing. It preserves Python's admin/owner membership gate, denial detail (`Access denied`), tenant existence check after role validation, tenant-scoped invoice list, `created_at DESC` ordering, and `{"invoices":[...]}` response shape over Python-owned `invoices`.
- Added exact Rust `GET /api/v1/tenants/:tenant_id/billing` for billing summary. It preserves the same admin/owner gate, tenant 404 behavior, tenant plan/storage projection, project/memory/distinct-user usage counts, `storage=0` parity with the current Python Project model, and most-recent 12 invoice projection over Python-owned tables.
- Added exact Rust `POST /api/v1/tenants/:tenant_id/upgrade` for owner-only plan upgrade. It preserves Python's owner-role gate (`Only owner can upgrade plan`), default `plan=pro`, `free/pro/enterprise` allowlist, storage-limit projection, tenant 404 after role validation, and `Plan upgraded successfully` response envelope over Python-owned `tenants`.
- Invoice child routes, wrong methods, and other billing writes stay Python-owned with gateway rollback coverage.
- Added server golden coverage for invoice list, billing summary, and upgrade response shapes plus live-gated Postgres adapter coverage for tenant role projection, tenant existence, tenant scoping, usage counts, created-desc invoice ordering/limit, and plan update persistence.
- Added exact Rust `GET /api/v1/support/tickets` and `GET /api/v1/support/tickets/:ticket_id` for current-user support ticket reads. The list endpoint preserves Python's current-user scoping, optional `tenant_id` membership gate with superuser bypass, optional `status`, `limit`/`offset` bounds, empty-string query behavior, `created_at DESC` ordering, total count, and `has_more` response shape over Python-owned `support_tickets`; the detail endpoint preserves the `id + user_id` lookup and `Ticket not found` 404 behavior.
- Added exact/method-scoped Rust `POST /api/v1/support/tickets`, `PUT /api/v1/support/tickets/:ticket_id`, and `POST /api/v1/support/tickets/:ticket_id/close` for current-user support ticket mutations. They preserve Python's tenant membership gate for tenant-scoped create, default priority `medium`, create status `open`, update-only `subject/message/priority`, current-user-only update/close, close status `closed`, resolved timestamp response shape, and `Ticket not found` 404 behavior.
- Added legacy-compatible Rust `/support/tickets`, `/support/tickets/:ticket_id`, and `/support/tickets/:ticket_id/close` method-scoped routes by reusing the same API-v1 handlers, preserving Python's duplicate router registration while keeping delete and unknown ticket children Python-owned with gateway rollback coverage.
- Added server golden coverage for support list response shape and live-gated Postgres adapter coverage for user scoping, tenant membership, status filtering, count, ordering, and pagination.
- Added exact Rust `GET /api/v1/data/stats` over the portable `GraphStore::stats` aggregate contract. The server preserves Python's project/tenant scope resolution (`Project not found`, project-tenant mismatch, project membership, tenant membership, and global-admin bypass), returns the Python `entities/episodes/communities/relationships/total_nodes/tenant_id/project_id` response shape, and keeps unsupported stats siblings Python-owned with rollback coverage.
- Added exact Rust `POST /api/v1/data/export` over the portable `GraphStore::export` raw graph contract. The route preserves Python's body flags (`include_episodes`, `include_entities`, `include_relationships`, `include_communities`), reuses the same Python-compatible tenant/project scope resolver, projects `Episodic` and `Community` graph entities into the Python export envelope lists, and keeps `GET /data/export` plus export child paths Python-owned rollback boundaries.
- Added exact Rust `POST /api/v1/data/cleanup` over new portable `GraphStore::count_episodes_older_than` / `delete_episodes_older_than` contracts. It preserves Python's query/body override order, `dry_run` default/boolean aliases, `older_than_days` validation/default, dry-run membership access, actual-delete tenant admin gate, actual-delete project owner/admin gate, global-admin bypass, and Python response fields while leaving wrong methods and child paths Python-owned.
- Added server golden coverage for data stats/export/cleanup, live-gated Postgres adapter coverage for the Python read/write authorization matrix, and in-memory/device/Neo4j graph adapter coverage for aggregate counts/export snapshots, cleanup delete side effects, and project scoping.
- Added exact Rust `GET /api/v1/projects/:project_id/schema/entities`, `/edges`, and `/mappings` for project schema collection reads. They use the existing Rust project access gate, return Python alias `schema`, and preserve project-scoped table reads over Python-owned schema tables.
- Added method-scoped Rust schema writes: `POST /api/v1/projects/:project_id/schema/entities`, `PUT/DELETE /api/v1/projects/:project_id/schema/entities/:entity_id`, `POST /api/v1/projects/:project_id/schema/edges`, `PUT/DELETE /api/v1/projects/:project_id/schema/edges/:edge_id`, `POST /api/v1/projects/:project_id/schema/mappings`, and `DELETE /api/v1/projects/:project_id/schema/mappings/:map_id`. They preserve Python's schema write roles (`owner|admin|member`), duplicate errors, create defaults (`status=ENABLED`, `source=user`), not-found details, and leave unsupported item reads/mapping updates Python-owned with rollback coverage.
- Added server golden coverage for entity type, edge type, edge map, entity mutation, and edge-map mutation response shapes plus live-gated Postgres adapter coverage for project scoping, JSON schema projection, schema write-role parity, CRUD helpers, duplicate detection, and no-op update timestamp behavior.
- Added exact Rust `GET /api/v1/artifacts` and `GET /api/v1/artifacts/:artifact_id` for artifact list/detail reads over Python-owned `artifacts`.
- Artifact reads preserve Python's project membership gate, category validation, `ready`-only list filtering, optional `tool_execution_id` filtering, newest-first ordering, post-limit `total` semantics, detail 404 behavior, and response shape including `metadata` and `created_at` wire formatting. The gateway exact-rule behavior routes the optional trailing slash collection to Rust, so the Rust server serves both `/api/v1/artifacts` and `/api/v1/artifacts/`.
- Added exact Rust `GET /api/v1/artifacts/categories/list` for authenticated static category discovery. It preserves Python's enum order, value/title label projection, and descriptions without touching storage or the `artifacts` table.
- Added method-scoped Rust `PUT /api/v1/artifacts/:artifact_id/content` for artifact content save-back. It preserves Python's project membership gate, `Artifact not found` 404, `Artifact cannot be updated in its current status` 400, UTF-8 body-to-bytes storage write, `size_bytes` update, and response envelope (`artifact_id`, `size_bytes`, `url`) while keeping presigned URL refresh out of the Rust ObjectStore port.
- Added method-scoped Rust `DELETE /api/v1/artifacts/:artifact_id` for artifact deletion. It preserves Python's project membership gate, object-store delete side effect, soft-deleted artifact row visibility (`status=deleted`), and response envelope (`status=deleted`, `artifact_id`) while leaving extra children and reserved category paths Python-owned.
- Artifact download, URL refresh, upload, multipart writes, and broader storage lifecycle remain Python-owned with gateway rollback coverage.
- Added server golden coverage for artifact list/detail/category-list/content-update/delete response shapes plus live-gated Postgres adapter coverage for project scoping, ready filtering, category/tool filtering, ordering, limiting, metadata projection, detail lookup, content-update metadata persistence, and soft-delete filtering from ready lists.
- Added exact Rust `GET /api/v1/attachments` and `GET /api/v1/attachments/:attachment_id` for attachment metadata reads over Python-owned `attachments`.
- Attachment reads preserve Python's conversation-scoped list, optional status validation/filtering, `created_at ASC` ordering, current-user project visibility filtering, project-tenant/attachment-tenant equality check, detail `Attachment not found` 404 behavior, and `Access denied to project` / `Access denied to attachment` negative controls.
- Added exact Rust `POST /api/v1/attachments/upload/simple` for small file upload. It preserves Python's project access gate, `purpose` enum validation, configurable size limits, MIME allowlist, default filename/content-type fallbacks, object-key shape, `uploaded` status, 24-hour expiration, ObjectStore write, and `AttachmentResponse` projection while leaving multipart initiation/part/complete/abort paths Python-owned.
- Added method-scoped Rust `DELETE /api/v1/attachments/:attachment_id` for attachment deletion. It preserves Python's authorization-before-side-effect flow, best-effort object-store delete semantics, hard deletion of the Python-owned `attachments` row, and response envelope (`success=true`, `message=Attachment deleted`) while leaving download children Python-owned.
- Added server golden coverage for attachment list/detail/simple-upload/delete response shapes plus live-gated Postgres adapter coverage for conversation scoping, status filtering, visible-project filtering, tenant mismatch hiding, detail lookup, superuser project-tenant access, object-key projection, simple-upload row insertion, and hard-delete row removal.
- Added exact Rust `GET /api/v1/projects/:project_id/cron-jobs`, `GET /api/v1/projects/:project_id/cron-jobs/:job_id`, and `GET /api/v1/projects/:project_id/cron-jobs/:job_id/runs` for project-scoped cron read-side coverage over Python-owned `cron_jobs` and `cron_job_runs`.
- Cron reads preserve Python response shapes (`items/total`, nested `schedule`/`payload`/`delivery` configs, run status/trigger fields), Python ordering (`created_at DESC, id ASC` for jobs and `started_at DESC, id ASC` for runs), disabled-job filtering default, and project scoping. Rust uses the existing project access gate, matching other already flipped project read surfaces.
- Cron write/runtime siblings stay Python-owned: create, update, delete, toggle, manual run, extra children, and APScheduler registration are covered by gateway rollback controls.
- Added server golden coverage for cron job list and run list response shapes plus live-gated Postgres adapter coverage for project scoping, disabled filtering, pagination, detail lookup, and run-history ordering.
- Added exact Rust `GET /api/v1/llm-providers/types` for authenticated static provider-type discovery. It preserves the Python `ProviderType` enum order and leaves all provider stateful/runtime routes Python-owned.
- Added exact Rust admin-only `GET /api/v1/llm-providers/env-detection`. It uses a shared Postgres-backed global admin gate, preserves Python's environment auto-detection order, duplicate alias suppression, local-provider optional API-key behavior, default model/base-url values, and plaintext `api_key` field shape, while keeping wrong-method and extra-child paths Python-owned.
- Added exact Rust read-only model catalog routes: `GET /api/v1/llm-providers/models/catalog`, `GET /api/v1/llm-providers/models/catalog/search`, and `GET /api/v1/llm-providers/models/:provider_type`.
- Rust uses the same embedded Python `models_snapshot.json`, preserves snapshot insertion order, fills the same `ModelMetadata` defaults, excludes Python's internal-only fields from API responses, and keeps provider-specific categorized lists on the `models.dev` source path before static fallback.
- Added method-scoped Rust `GET /api/v1/llm-providers/:provider_id/health` for latest persisted provider health reads over Python-owned `provider_health`. It preserves Python's newest `last_check` selection, UUID validation boundary, 404 detail when no health row exists, and response shape without decrypting provider credentials or performing active checks.
- Added method-scoped Rust `GET /api/v1/llm-providers/tenants/:tenant_id/assignments` for tenant-provider assignment list reads over Python-owned `tenant_provider_mappings`. It preserves Python's tenant member or admin access gate, optional `operation_type` enum filter, priority ordering, and mapping response shape without resolving/decrypting provider configs.
- Added method-scoped Rust `GET /api/v1/llm-providers/:provider_id/usage` for provider usage statistics over Python-owned `llm_usage_logs`. It preserves Python's admin-vs-default-tenant scoping, provider/date/operation filters, grouped token/cost totals, and `avg_response_time_ms: null` contract.
- Graph-store and retrieval-store type/list/detail plus metadata create/update/delete routes are now Rust-owned with shared Python AES-GCM config encryption/decryption, masked response goldens, admin-gated writes, name-conflict/env-store/in-use negative controls, and gateway rollback coverage. Graph/retrieval live connection test routes remain Python-owned because they validate live backend state. Provider list/detail remain deliberately deferred because Python response construction also reads process-local resilience state; Rust should not flip those paths until the shared provider runtime-state contract is implemented and covered.
- Model catalog refresh remains Python-owned because it performs a server-side models.dev network fetch and rewrites the local snapshot artifact. Active provider health checks remain Python-owned because they call external provider APIs and write `provider_health`. Tenant assignment mutations and tenant provider resolution remain Python-owned because they write mapping state or return masked provider configs. System resilience status/reset remains Python-owned because it reads and mutates process-local circuit breaker/rate limiter registries.
- Added exact Rust provider metadata CRUD/list/detail for `GET/POST /api/v1/llm-providers/` and `GET/PUT/DELETE /api/v1/llm-providers/:provider_id`. It preserves Python's collection trailing-slash shape, admin gate on writes, non-admin inactive-provider hiding, soft-delete semantics, operation-specific model column separation, local-provider no-key sentinel, API key AES-GCM envelope compatibility, masked response key projection, latest persisted health fields, and default resilience status projection while active connection tests stay Python-owned.
- Added server golden coverage for provider config response, provider type discovery, env detection, catalog list/search, provider-model, latest provider-health, tenant-assignment-list, and provider-usage responses plus gateway rollback controls proving catalog refresh, active health-check, assignment mutations/provider resolution, system resilience runtime, extra children, and wrong-method calls remain Python-owned.
- Added exact Rust `GET /api/v1/deploys/`, `GET /api/v1/deploys/:deploy_id`, and `GET /api/v1/deploys/instances/:instance_id/latest` for deploy read-side coverage over Python-owned `instances` and `deploy_records`.
- Deploy reads preserve the Python trailing-slash collection contract, tenant access gate (`instances.tenant_id` + `user_tenants`, with superuser bypass), response shape (`deploys/total/page/page_size` and deploy fields), and created-desc ordering. Rust filters deleted instances/deploys at the API visibility boundary already used by Python's access checks.
- Deploy create, success/failed/cancel lifecycle transitions, and Redis/SSE progress remain Python-owned with gateway rollback controls.
- Added server golden coverage for deploy list response shape plus live-gated Postgres adapter coverage for tenant access projection, superuser bypass, missing/forbidden access states, list ordering, detail lookup, and latest lookup.
- Added exact Rust `GET /api/v1/instances/` and `GET /api/v1/instances/:instance_id` for current-default-tenant instance reads over Python-owned `instances`.
- Instance reads preserve Python's default tenant dependency (`user_tenants` ordered by `created_at ASC, id ASC`), trailing-slash collection contract, `deleted_at IS NULL` filtering, `created_at DESC, id ASC` ordering, and `instances/total/page/page_size` response shape.
- Added exact Rust `GET/PUT /api/v1/instances/:instance_id/config` and `GET/PUT /api/v1/instances/:instance_id/llm-config` as narrow projections/mutations of the already authorized instance detail.
- Config and LLM-config paths preserve Python's default-tenant ownership check, config response shape (`env_vars`, `advanced_config`, `llm_providers`), full-object config replacement, LLM provider/model projection, `api_key_override` preservation/default-null behavior, and Python `bool(api_key_override)` semantics.
- Added method-scoped Rust `PUT /api/v1/instances/:instance_id/config/pending` for pending config staging over Python-owned `instances`.
- Pending config staging preserves Python's default-tenant ownership check, object-shaped `pending_config` request validation, `updated_at` refresh, full `InstanceResponse` shape, and rollback coverage for general config writes plus config apply.
- Added exact Rust `GET /api/v1/instances/:instance_id/members` for instance member list reads over Python-owned `instance_members` plus `users`.
- Instance member list reads preserve Python's default-tenant ownership check, `limit`/`offset` bounds, `deleted_at IS NULL` filtering, `created_at ASC, id ASC` ordering, joined `user_name`/`user_email` projection, `user_avatar_url: null`, and `has_more` response calculation.
- Added exact Rust `GET /api/v1/instances/:instance_id/members/search-users` for tenant-user member search over Python-owned `users` plus `user_tenants`.
- Instance member user search preserves Python's default-tenant ownership check, active tenant-user filtering, optional `q` search over `email`/`full_name`, `limit` bounds, `full_name ASC, email ASC` ordering, and direct list response shape.
- Added method-scoped Rust instance member mutations: `POST /api/v1/instances/:instance_id/members`, `PUT /api/v1/instances/:instance_id/members/:member_id`, and `DELETE /api/v1/instances/:instance_id/members/:user_id`.
- Instance member mutations preserve Python's default-tenant ownership check, UUID member id generation, role enum validation (`admin|editor|user|viewer`), duplicate-member 400 behavior including soft-deleted duplicates, update-by-member-id, soft-delete-by-user-id, joined user projection, 204 delete response, and rollback controls for wrong methods/unsupported siblings.
- Added exact Rust `GET /api/v1/instances/:instance_id/channels` for instance channel config list reads over Python-owned `instance_channel_configs`.
- Instance channel list reads preserve Python's instance-exists-first check, tenant membership/global-admin access gate, `deleted_at IS NULL` filtering, `created_at DESC` ordering, `items` response wrapper, and `InstanceChannelConfig` serialized field shape including null timestamps.
- Instance create/update/delete, scale/restart, config apply, instance files, and channel create/update/delete/test remain Python-owned with gateway rollback controls.
- Added server golden coverage for instance list, config, pending-config update, LLM-config, LLM override, member-list, member mutation, user-search, and channel-list response shapes plus live-gated Postgres adapter coverage for default-tenant selection, tenant scoping, deleted-row filtering, list ordering, detail lookup, wrong-tenant detail 404, config/pending/LLM config updates, member ordering/pagination/user projection/mutations, user-search filtering/ordering, channel ordering/filtering, and tenant channel access projection.
- Added exact Rust `GET /api/v1/genes/` and `GET /api/v1/genes/:gene_id` for gene marketplace list/detail reads over Python-owned `gene_market`.
- Gene reads preserve Python's default tenant dependency (`user_tenants` ordered by `created_at ASC, id ASC`), explicit `tenant_id` access validation, global published-public inclusion, tenant-local slug shadowing over global slugs, slug request-order projection, `exclude_installed_instance_id` tenant guard, `deleted_at IS NULL` filtering, `created_at DESC, id ASC` ordering for non-slug lists, and `genes/total/page/page_size` response shape.
- Added exact Rust `GET /api/v1/genes/genomes` and `GET /api/v1/genes/genomes/:genome_id` for genome marketplace list/detail reads over Python-owned `genomes`.
- Genome reads preserve the same default/explicit tenant access gate, global published-public inclusion, search/visibility/published filters, `deleted_at IS NULL` filtering, `created_at DESC, id ASC` ordering, and `genomes/total/page/page_size` response shape.
- Gene/genome create/update/delete, publish/unpublish, install/uninstall, ratings, reviews, and evolution events remain Python-owned with gateway rollback controls.
- Added server golden coverage for gene and genome list response shapes plus live-gated Postgres adapter coverage for default-tenant selection, tenant access projection, global visibility filtering, gene slug ordering/shadowing, gene exclude-installed filtering, genome ordering, deleted-row filtering, and detail lookup.

Groups:

1. Genes and instances: gene list/detail, genome list/detail, instance list/detail reads, instance config/LLM-config reads and writes, instance pending-config staging, instance member list/search/mutations, and instance channel config list reads delivered; gene/genome writes/install/reviews/ratings/evolution and all instance write/runtime/config-apply/file/channel mutation-test paths remain future.
2. LLM providers, deploy, cron, store metadata, and maintenance: provider metadata list/detail/create/update/soft-delete, provider type discovery, admin-only env detection, read-only model catalog/list/search/provider-models, latest persisted provider-health reads, tenant assignment list reads, provider usage statistics reads, graph/retrieval-store type/list/detail plus metadata create/update/delete, legacy sandbox profile discovery, cron list/detail/run-history reads, deploy list/detail/latest reads, and maintenance status reads delivered; model catalog refresh, active provider health checks/writes, tenant assignment mutations/provider resolution, system resilience runtime/reset, graph/retrieval-store live connection tests, legacy sandbox lifecycle/create/tools/services/events, cron writes/runtime, deploy writes/lifecycle/progress, and maintenance refresh/optimization/invalidation mutations remain future.
3. Observability, audit, events, and DLQ: event replay filtering, event list/type reads, audit list/filter/runtime-hook summary/export reads, and admin DLQ list/detail/stats/retry/discard/cleanup delivered; event writes and audit write paths remain future.
4. Notifications and webhooks: current-user notification list/mutations and tenant webhook CRUD delivered; webhook provider delivery remains future.
5. Billing, support, and export: tenant billing summary, tenant invoice list, owner-only plan upgrade, API-v1 plus legacy support ticket list/detail/create/update/close, exact data stats/export/cleanup delivered; remaining data/support siblings remain future.
6. Schema, artifacts, and uploads: schema collection reads and method-scoped schema CRUD, artifact list/detail/category-list reads, artifact content save-back, artifact soft-delete, attachment list/detail metadata reads, attachment simple upload, and attachment hard-delete delivered; artifact download/refresh/upload/multipart lifecycle, attachment multipart upload/download paths, and broader uploads remain future.

Per-group checklist:

- Repo/schema parity.
- Rust endpoint.
- Golden.
- Gateway method rule.
- Rollback test.
- Python negative control.

Acceptance evidence:

- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server events_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres tenant_event_log -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server audit_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres audit -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server admin_dlq_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-redis redis_dlq_reads_python_keys_filters_and_stats -- --nocapture` (live-gated; skips when Redis is unavailable)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-redis redis_dlq_retry_republishes_to_unified_event_stream -- --nocapture` (live-gated; skips when Redis is unavailable)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres admin_access_repository_matches_python_admin_gate -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server notifications_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres notifications -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server billing_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres billing -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server support_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres support_tickets -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-secrets python_aes -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-secrets aes256 -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres backend_store -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server graph_store -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server retrieval_store -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server data_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres data_stats -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-mem graph::tests::stats_counts_special_entity_types_and_scopes -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-device graph::tests::stats_counts_special_entity_types_and_scopes -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server tenant_webhooks_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres tenant_webhooks -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server schema_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres project_schema -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server artifacts_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres artifacts -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway routing -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server attachments_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres attachments -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server cron_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres cron -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server llm_providers_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres llm_provider_crud_writes_python_encrypted_metadata_rows -- --nocapture` (live-gated; skips when `DATABASE_URL` or `LLM_ENCRYPTION_KEY` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres llm_provider_latest_health_matches_python_ordering -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres llm_provider_tenant_assignments_match_python_access_filter_order -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres llm_provider_usage_statistics_match_python_scope_and_aggregation -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server deploy_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres deploy -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server instance_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres instances -- --nocapture` (live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-server gene_api -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-postgres genes -- --nocapture` (gene + genome read coverage; live-gated; skips when `DATABASE_URL` is unset)
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway routing::tests -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway strangled_prefixes_route_to_rust -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway everything_else_routes_to_python -- --nocapture`
- `cargo test --manifest-path agi-stack/Cargo.toml -p agistack-gateway gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough -- --nocapture`

## I7 Platform Release Hardening

Goal: support real multi-endpoint launch claims.

Delivered in this checkpoint:

- Added an `agi-stack Bench Scorecard` CI job that installs stable Rust and runs `make bench`.
- The bench binary already enforces its go/no-go thresholds through its process exit code, so CI now blocks on scorecard regressions.
- The bench binary now writes a structured JSON report to `target/bench/scorecard.json` by default, or to `AGISTACK_BENCH_REPORT` when set.
- The bench binary now includes stable row ids and numeric metric payloads, and can compare against `AGISTACK_BENCH_BASELINE` with `AGISTACK_BENCH_REGRESSION_TOLERANCE_PCT` to fail on historical regressions.
- The CI bench job restores the most recent branch-local approved scorecard cache into `target/bench/baseline/scorecard.json`, passes it as `BENCH_BASELINE`, and saves the current scorecard back only when the bench job succeeds.
- Added `scripts/bench-trend-summary.py` to append the current recommendation, threshold failures, baseline regressions, and top metric deltas to the GitHub Actions step summary.
- The CI bench job uploads `agi-stack-bench-scorecard` as an artifact even when the scorecard fails, giving release reviews a durable regression record.
- Added a WASM persistence snapshot surface: `AgistackCore.exportSnapshot()` returns versioned JSON for the in-memory memories, and `AgistackCore.importSnapshot()` restores memories and rebuilds the semantic vector index.
- Added a browser-host persistence module for the WASM binding: `openIndexedDbSnapshotStore()` stores versioned snapshots in IndexedDB, `saveCoreSnapshot()` / `restoreCoreSnapshot()` expose explicit save/restore, and `createPersistentAgistackCore()` wraps ingest with host-store autosave while keeping IndexedDB out of the Rust core.
- Extended the `wasm-web` smoke test so a fresh `AgistackCore` instance imports the snapshot and proves keyword plus semantic search survive reload-style reconstruction, then exercises the host-store contract, IndexedDB get/put/delete behavior through a deterministic mock, and persistent-core facade through the deterministic in-memory host store.
- Extended the WASM host-store smoke to exercise IndexedDB upgrade recovery when an existing database is missing the snapshot store, and to assert IndexedDB open failures propagate cleanly for offline/error states.
- Fixed the browser host store to recover from real IndexedDB `VersionError` after an automatic missing-store upgrade by reopening the existing database at its current version before continuing the normal store check.
- Added a dependency-free real-browser smoke runner (`browser-smoke.mjs`) that launches local Chrome Headless over CDP, serves the web package, and proves real IndexedDB reload restore, missing-store version upgrade, and CDP offline persistence. The runner exits cleanly with `BROWSER_SMOKE_SKIP` when Chrome is unavailable.
- `make wasm-web` now emits both the nodejs smoke package (`pkg`) and a browser ESM package (`pkg-web`), and the packaging prep step copies `web-persistence.mjs` plus records it in each generated package's `files` allowlist.
- `make wasm-web` now runs the Chrome CDP browser smoke after the browser ESM package is prepared, so local/CI environments with Chrome exercise the real browser path in addition to the deterministic Node smoke.
- Added `make desktop-bundle` as the explicit Tauri packaging target and a macOS CI job that installs `tauri-cli`, runs the bundle, and uploads `apps/desktop/src-tauri/target/release/bundle/**` as a release-review artifact.
- Added `make desktop-bundle-smoke` and `scripts/check-desktop-bundle.sh` to validate the generated bundle directory, Tauri identifier, frontend dist, and macOS `.app` main binary/Info.plist before CI uploads the artifact.
- Made the Android NDK toolchain host tag portable between macOS (`darwin-x86_64`) and Linux (`linux-x86_64`) with an overrideable `NDK_HOST_TAG`.
- Added unsigned Android and iOS CI artifact jobs: Android installs NDK r30, runs `make android`, and uploads the `.so` plus Kotlin bindings; iOS runs `make ios` on macOS and uploads the XCFramework plus generated Swift/header outputs.
- Added UniFFI mobile binding microbenchmarks to the bench scorecard. The bench opens the real `MobileCore` SQLite-backed surface, records ingest/search/semantic-search P50/P99 metrics into `target/bench/scorecard.json`, and lets the existing baseline comparator fail future regressions.
- Added exact public Rust `GET /api/v1/engines` for runtime engine catalog discovery. It preserves Python's Python 3.12, Node.js 22, and MemStack Sandbox catalog order and metadata while sandbox lifecycle, image management, and engine execution remain Python-owned with rollback coverage.
- Added exact authenticated Rust `GET /api/v1/system/features` and `GET /api/v1/system/info` for system metadata discovery. They preserve Python's feature definitions, `MEMSTACK_EDITION` enterprise gating, agent runtime mode, memory runtime mode, memory tool-provider normalization, and failure-persistence flag while system runtime siblings remain Python-owned with rollback coverage.
- Added exact authenticated Rust `GET /api/v1/maintenance/status` for maintenance status reads. It uses the portable GraphStore stats/count ports, preserves Python recommendation thresholds and project-scope boundaries, and keeps maintenance refresh/optimization/invalidation mutations Python-owned with rollback coverage.

Sequence:

1. Web: real Chrome reload/offline/upgrade recovery tests are delivered for the IndexedDB host store, alongside deterministic in-memory/fake-IndexedDB smoke. Evaluate wa-sqlite only if snapshot-size or query-shape evidence requires it.
2. Desktop: static bundle smoke is delivered; add updater metadata, platform entitlements, and real install/launch smoke on top of the delivered macOS CI bundle artifact.
3. Android/iOS: add signing/distribution lanes on top of the delivered unsigned artifact CI jobs and UniFFI microbenchmarks.
4. Bench: extend the delivered branch-local cache baseline into a release-channel baseline once signed release artifacts exist.

Acceptance evidence:

- `make wasm-web` proves snapshot export/import survives reload-style reconstruction, validates deterministic in-memory plus IndexedDB-mock stores, and runs real Chrome IndexedDB reload/offline/upgrade smoke when Chrome is available (`BROWSER_SMOKE_SKIP` documents environments without Chrome).
- Desktop bundle is produced, statically smoke-checked, and uploaded by macOS CI; real install/launch smoke remains required.
- Android/iOS unsigned CI artifacts are built and uploaded; signed distribution lanes remain required.
- Bench scorecard CI job blocks release on owned thresholds, restores the previous approved baseline, uploads the persisted JSON report, supports historical baseline regression failures, publishes a trend summary, and now records mobile UniFFI binding latency.
