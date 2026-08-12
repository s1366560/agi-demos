# Workspace Core event, Agent, and migration gate evidence

Date: 2026-08-11

This record separates source/fixture contracts from evidence that must come from a live Core,
Ray execution, and a production-scale snapshot. A passing fixture is never promoted to live or
production evidence.

## Current gate result

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| Full structured event parity | PASS | All 166 Python event types are classified: 2 internal-only and 164 Web-visible. Web routes all 164 as 139 Agent events plus 25 Workspace events; 48 have canonical timeline routes, 7 are intentionally live-only, and 0 are unclassified. The original 35/35 Workspace migration subset remains exact. |
| Terminal event mapping | PASS | 3 provider terminal mappings bind execution status, timeline history, durable outbox, and pipeline progression. |
| Python Provider component E2E | PASS | Real `AvernetProviderAdapter`, `MemStackAgentRuntimeProvider`, and `AvernetBotEventHttpSink` with fake DB/Core/Agent services and `httpx.MockTransport`. This is not live HTTP, PostgreSQL Core, or Ray evidence. |
| Live HTTP/Core/Ray Agent E2E | PASS | A dedicated API and PostgreSQL Core completed two `chat.send` runs, `chat.inject`, durable `chat.history`, duplicate replay, three terminal/outbox proofs, and an active `chat.abort` against the running Ray Agent service. The abort cancelled the detached local worker; Ray cancellation was not needed. |
| Three-run fixture migration rehearsal | PASS | Three `dry-run -> execute -> validate -> reverse-export` repetitions over 50 fixture source rows. Synthetic clock values are test assertions, not measured production timings. |
| Three-run local PostgreSQL snapshot rehearsal | PASS | Three measured `dry-run -> execute -> validate -> reverse-export` runs over the local development snapshot: 174 copied legacy dependency rows produced 134 mapped source records; snapshot hash and zero-orphan validation were identical on every run. This is real PostgreSQL evidence, but not production-scale evidence. |
| Three-run local PostgreSQL restore rehearsal | PASS | Each 114-row reverse export restored into a fresh PostgreSQL database. Source counts, entity hashes, snapshot hash, and zero-orphan validation matched; measured recovery was 0.927-0.987 seconds. This is not a production recovery-time claim. |
| Three production-scale snapshot rehearsals | BLOCKED | No production snapshot identity/count/hash or executable legacy restore verifier was supplied. No production evidence file was written. |

## Event parity result

Command:

```bash
uv run python scripts/workspace-core/verify-event-parity.py
```

Observed result:

```json
{"authorityCounts":{"avernet-core":24,"memstack-agent-runtime":11},"contractSha256":"1c3afd58b335467de1a76c82dada3cd02f005bde4a003eb5e3fa9760f387a0b6","eventCount":35,"fullEventAudit":{"canonicalTimelineRouteCount":48,"eventCount":166,"frontendEventCount":164,"internalEventCount":2,"liveOnlyCanonicalRouteCount":7,"ok":true,"unclassifiedEventCount":0,"webAgentRouteCount":139,"webGeneratedEventCount":164,"webWorkspaceRouteCount":25},"manifestVersion":"workspace-events-v1","ok":true,"terminalMappingCount":3,"terminalSurfaceCount":4}
```

The verifier checks exact enum coverage across Python and generated Web types, every Web routing
authority, canonical timeline handling, envelope fields, payload requirements, delivery ordering,
idempotency/replay metadata, source evidence, terminal status mapping, and the four terminal
surfaces. The contract manifest is
`docs/architecture/workspace-core-event-parity-manifest.json`.

## Agent Runtime evidence

The component E2E covers:

- `chat.send`, `chat.inject`, `chat.history`, and `chat.abort`;
- Provider event serialization to `/bot/events`;
- terminal persistence before callback publication;
- execution status, timeline history, outbox, and pipeline progression consistency;
- duplicate delivery replay without a second Agent execution, history append, outbox write, or
  pipeline progression.

The live gate is `scripts/workspace-core/verify-live-agent-e2e.py`. It accepts credentials only
from the environment, never serializes credential material, and requires all of the following
before writing evidence:

1. MemStack API health;
2. a `memstack-workspace-core/*` health response;
3. an authenticated complete Workspace public API capability declaration;
4. a running Ray `src.agent_actor_worker` driver;
5. two successful `chat.send` executions with durable Core terminal/outbox proofs;
6. `chat.inject` before the second send and durable `chat.history`;
7. duplicate `chat.send` with unchanged durable history;
8. `chat.abort` observing cancellation of an active Ray or local execution.

Passing live invocation:

```bash
uv run python scripts/workspace-core/verify-live-agent-e2e.py \
  --evidence-output \
  docs/architecture/workspace-live-agent-e2e-evidence-2026-08-11.json
```

The live evidence declares `evidenceClass=live-http-core-ray`, `liveEvidence=true`, and `ok=true`.
Core and API health, 92/92 Core capability, the running Ray worker, Workspace scope, active Agent,
and migrated Group/Session projections all passed preflight. The run then produced 50 durable
history messages, stable history across duplicate delivery, three distinct terminal/outbox proofs,
and an observed active cancellation (`localWorkerCancelled=true`, `rayCancelled=false`). No
credential material is serialized.

The first attempt exposed a real configuration defect in the gate: an LLM provider UUID had been
passed as the BCS Provider identity, so Core correctly rejected `/bot/events` with `run_not_found`.
The gate now fail-fast requires the reserved identity `memstack-workspace-agent-runtime`, validates
the Workspace/Agent projection, and requires Group/Session IDs to match the migrated Workspace
projection before starting an Agent side effect.

Required environment for a real run:

- `WORKSPACE_E2E_CORE_BASE_URL` or `WORKSPACE_CORE_BASE_URL`;
- `WORKSPACE_E2E_PROVIDER_WEBHOOK_TOKEN` or `WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN`;
- `WORKSPACE_E2E_CORE_SERVICE_TOKEN` or `WORKSPACE_CORE_SERVICE_TOKEN`;
- `WORKSPACE_E2E_TENANT_ID`, `WORKSPACE_E2E_PROJECT_ID`, `WORKSPACE_E2E_WORKSPACE_ID`;
- `WORKSPACE_E2E_USER_ID`, `WORKSPACE_E2E_AGENT_ID`;
- `WORKSPACE_E2E_PROVIDER_ID=memstack-workspace-agent-runtime`;
- `WORKSPACE_E2E_GROUP_ID` and `WORKSPACE_E2E_SESSION_ID`, both matching the migrated Workspace ID;
- `WORKSPACE_E2E_ABORT_MESSAGE` describing a safe task long enough to cancel.

## Migration rehearsal evidence

The fixture harness proves runner behavior, not production scale:

- exactly three rehearsals;
- 25 records in each of two fixture entities, for 50 source records per rehearsal;
- synthetic `0.5s` migration-plus-validation and `0.25s` reverse-export values per rehearsal;
- a second eight-record fixture verifies restore count, primary-key hash, content hash, snapshot
  hash, zero orphans, and synthetic `0.4s` recovery per rehearsal;
- evidence and reverse exports are written atomically.

The local PostgreSQL snapshot rehearsal is separate from the fixture harness. It copied 174 legacy
dependency rows into an isolated source database, then measured three full migration runs over 134
mapped records. All three runs produced snapshot SHA-256
`962cd2bc2253e9a3c62d3f4376c011e49799df95f06101b51c9daa94d3d1eec7`, zero orphans, and the same
114-row reverse export. Migration plus validation took 0.347-0.394 seconds. Each export was then
restored into a newly created PostgreSQL database; the three measured recoveries took 0.987,
0.951, and 0.927 seconds and reproduced record counts, entity hashes, the snapshot hash, and zero
orphans. The evidence files are:

- `/tmp/avernet-closeout-evidence.WOPt66/local-postgres-snapshot-rehearsal.json`;
- `/tmp/avernet-closeout-evidence.WOPt66/local-postgres-restore-rehearsal.json`;
- `/tmp/avernet-closeout-evidence.WOPt66/local-postgres-snapshot-exports/`.

Those files deliberately declare `productionEvidence: false`. The local snapshot contains only
134 mapped records, so its fast timings cannot satisfy or predict the production-scale gate.

Production mode additionally requires a full unscoped snapshot, declared source record count,
declared snapshot SHA-256, an executable external legacy restore verifier, at most 70 minutes for
migration plus validation, and at most 15 minutes for reverse export plus restore.

Current fail-closed invocation:

```bash
uv run python scripts/workspace-core/run-migration-rehearsals.py \
  --run-id production-readiness \
  --snapshot-id missing-production-snapshot \
  --evidence-output /tmp/workspace-production-rehearsal-blocked.json \
  --export-directory /tmp/workspace-production-rehearsal-exports \
  --production-scale
```

It exited `2` at the missing expected source record count. No production evidence file was
created. A real run must additionally provide `--expected-source-records`,
`--expected-snapshot-sha256`, and `--restore-verifier`; the snapshot values must come from the
authoritative production-scale snapshot, not a generated fixture.

## Validation baseline

Focused validation:

```bash
uv run pytest \
  src/tests/unit/infrastructure/workspace_core/test_event_parity_manifest.py \
  src/tests/unit/infrastructure/workspace_core/test_agent_runtime_provider.py \
  src/tests/unit/infrastructure/workspace_core/test_migration_rehearsal_runner.py \
  src/tests/unit/infrastructure/workspace_core/test_live_agent_e2e_gate.py -q
```

The final combined Workspace Core/Gateway/configuration/migration run passed 147/147 Python tests;
the Web event router/SSE run passed 49/49 tests. Ruff and formatting checks pass, and Pyright reports
0 errors and 0 warnings for the live gate. Route and implementation manifests remain 92/92, the
event verifier reports zero unclassified events, and `git diff --check` passes. The live evidence
SHA-256 is `fe372b42e5eae133fd1401110730de43efde37d8e39182a9f78ea6e3b7c1eed5`.

The development PostgreSQL database was upgraded with `make db-migrate`; `alembic current` and
`alembic heads` both report `727ce1982b0f (head)`.

Release implication: event structure, component Agent behavior, and rehearsal machinery are
implemented; Live Agent/Core/Ray E2E passes, and a local PostgreSQL snapshot has completed three
measured migration and recovery cycles. The release gate remains No-Go until all three real
production-scale rehearsals pass and the separate Desktop signing/notarization/updater release
gates are satisfied.
