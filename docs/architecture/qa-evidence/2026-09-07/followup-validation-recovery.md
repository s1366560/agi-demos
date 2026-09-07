# Follow-up validation and recovery

These results extend the implementation ledger. They do not close the combined
knowledge/synchronization and cloud/local automation release gates.

## Frozen Desktop and Web

- Desktop at `13ab5d214`: 4292 passed, 0 failed, 0 skipped. The suite used the real
  canonical Sidecar and Workspace Core binaries. Web inventory, V2/V3/V4 generators,
  and V3/V4 structural closure checks passed. Formal parity evidence remains
  `source_content_integrity_only`, with `execution_evidence=false`.
- Evidence: `/var/tmp/knowledge-parity-2786be19c-3dmDMU/final-verification.json`,
  `desktop-final-committed.log`, and `canonical-final-checks.log` in the same directory.
- Web: 3656 passed with four workers; TypeScript passed. Evidence:
  `/tmp/memstack-web-frozen-four-workers.log`, `/tmp/memstack-web-frozen-types.log`.

## Backend fixture corrections

- `89652a08e`: Agent Run generation fixture explicitly implements Redis cache and
  event-publisher protocols. All 11 tests passed; no production protocol was relaxed.
  Evidence: `/tmp/memstack-agent-run-api-green.log`.
- `7d1b4c405`: Session projection publishes its workspace adapter after test setup;
  episodes/recall publish the graph adapter through the generation factory. Original
  scope and sensitive-field assertions remain; recall assertions now check the
  current port's result and arguments. All 7 tests passed. Evidence:
  `/tmp/memstack-session-projection-final.log`, `/tmp/memstack-episodes-recall-final.log`.
- `75e40e59f`: Search shape contracts use a fixed extraction response before real
  Neo4j writes/searches. Generic test prose previously produced no entities. All 7
  graph contract tests passed; extraction semantics remain outside these two search
  primitive tests. Evidence: `/tmp/memstack-graph-contract-full.log`.
- Ruff, formatting, staged scope checks and credential scans passed for these edits.
  Rollback affects test preparation only.

## Interrupted full Backend run

The full `src/tests` run collected 16879 tests. It reproduced the fixture failures
above and the sandbox connection failure under separate investigation. At about 3%
it developed cascading errors while parallel isolated Rust builds exhausted disk.
The process exited with code 120 and could not write its JUnit report. Its log is
`/tmp/memstack-followup-backend-collection-fixed.log`; this is not full-suite evidence.

Only rebuildable Rust incremental caches were removed from the task worktrees and
canonical `agi-stack/target/debug/incremental`. Existing binaries and application
data were retained. Free space recovered to approximately 25 GiB. Subsequent Rust
builds are serialized with incremental compilation disabled. The subsequent unit
run was paused after 1619 passed because Docker Desktop remained unhealthy. Evidence:
`/tmp/memstack-followup-unit-frozen.log` and its JUnit XML. It is not a full unit pass.

Docker Desktop recovered after its official force-stop/restart commands. The four
existing PostgreSQL/Redis/Neo4j/MinIO containers were started without recreation or
data deletion; these and Workspace Core became healthy. API `/health` returned 200.
Free space was approximately 27 GiB. Full verification must follow the next merge.
