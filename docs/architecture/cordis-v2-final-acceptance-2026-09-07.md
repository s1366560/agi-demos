# Cordis V2 final acceptance and V1 retirement

The approved eight-stage architectural plan has completed its implementation,
operational V1 retirement and native acceptance in the `codex/cordis-v2` checkout.
The final runtime commit is `2b6424699`. Real startup and shutdown both completed
after the scheduler ownership and post-publication activation fixes. This records
the local deployment and explicit acceptance boundaries; no remote service was deployed.

## Final regression evidence

| Gate | Verified result and boundary |
| --- | --- |
| Python V2 unit directory | 1,637 passed, 21 warnings, 2,122.02 seconds; started from clean `30cfb40d8`, a full baseline before the latest Host and SkillEvolution changes, which have focused regression evidence below |
| Rust protocol | 28 passed |
| Rust server | 607 passed, including the post-native-tool-contract run |
| Native tool-contract affected Rust crates | 795 passed; overlaps with other Rust runs, not an additive total |
| Complete Rust formatting | `cargo fmt --all -- --check` passed in an isolated worktree at `ac0420733`, including the regenerated Rust catalog; no Rust changes in `2b6424699` |
| Latest full Desktop suite | 4,131 passed, two skipped, zero failed, 124.993 seconds, at `ac0420733`; Desktop and parity sources are unchanged in `2b6424699` |
| Full production profile with real HTTP/PostgreSQL | Passed; 436 entries, actual Python API, SidecarSupervisor and production renderer factory; independent sidecar/renderer rejection retained each prior good identity |
| Production renderer extraction wiring | 192 passed |
| Provider startup preservation | 11 isolated tests passed; no original-database fixture |
| Retirement persisted-source fix | Eight new tests plus 15 existing service/CLI/preflight regressions passed; Ruff and Pyright passed |
| Scheduler task ownership | 17 focused tests passed; real APScheduler/PostgreSQL/Redis startup and same-task shutdown also passed |
| Post-admission background activation | 12 SkillEvolution and 27 focused Host tests passed; 28 existing Host regressions also passed |
| ROOT startup and persisted-source fence | All eight startup and seven restore-fence tests passed after correcting an unreceipted test fixture |
| Final DI and transport boundary | 19 DI, nine real repository-lease and 45 Provider/recovery tests passed; no static business DI fallback |
| Retired workspace launch cleanup | 76 retained-behavior/retirement tests passed; Ruff passed and Pyright zero errors (174 existing warnings) |
| Protocol generation and contract inventory | Both checks passed in an immutable `ac0420733` snapshot and after final DI changes; existing TypeScript dependency supplied to the snapshot for completeness checking |

The final full Desktop log is `cordis-final-desktop-ac0420733.log`. Tests are
reported at their actual boundaries, rather than presented as one combined run on
the final documentation commit. The original Python V2 full-suite baseline remains
valid historical evidence; subsequent runtime changes have their focused results
listed above. The final DI cleanup changes only Python boundaries and unreachable
workspace code; it does not change manifests, generated catalogs or the Desktop
parity source proofs. Strict Clippy still reports existing diagnostics at unchanged
statements; it is not counted as passing.

Parity artifacts are committed and consistently bind audited source revision
`259dc96d26c5e3f16d2330384b068670bfd6cee0`. V2 covers 66 capabilities, 178 routes
and 96 sources; V3 covers 66 capabilities and 73 journeys; V4 covers 67 capabilities,
74 journeys and 24 overrides. Source verification is explicitly not execution
evidence. Existing partial/degraded/unavailable classifications remain unchanged;
this architectural closeout does not claim every product feature has full UI parity.

## Actual native operation

The Electron client was built and launched through the canonical repository-root
command `make -C agi-stack run-desktop`, using the task-owned QA profile and workspace.
A temporary Kimi provider completed creation, rename, connection/model discovery,
disable/re-enable, an actual model/tool operation, and deletion after restoring the
original default provider. Credentials were supplied by an environment reference.

Conversation `6b326d64-1236-5fde-b371-fc42e4598e14`, titled
`Cordis Tool Contract Native Acceptance`, submitted a valid structured plan through
the real provider. After native approval, the model returned
`CORDIS_FINAL_NATIVE_KIMI_OK 437`. A full exit and canonical relaunch preserved the
plan, answer and completed status. A later restart also preserved deletion of the
temporary provider and the original two-provider registry/default route. The final
canonical rebuild/relaunch at `ac0420733` again restored this conversation, structured
tool record, completed reply and provider registry. This final check is restart
persistence evidence, not a newly executed model turn.

The stale accessibility loading placeholder was contradicted by both original and
later screenshots showing the correct completed-run input restriction. The proposed
UI loading change was withdrawn before commit. Failed earlier model attempts remain
in the evidence; they are not counted as acceptance.

## Real original database and runtime composition

The original PostgreSQL database underwent the complete standard Alembic upgrade
from `822cd9402ce6` to `e83f7c901b52`. No table creation shortcut or revision stamping
substituted for those migrations. The real `main:app` and canonical-built Rust Core
then completed startup using the original PostgreSQL, Redis and Neo4j services.
The first run logged Neo4j authentication failures; the final launcher resolved the
existing matching password in memory, verified a real read-only query, and the
final runtime log confirms successful Neo4j connection and index initialization.
No password or repository dotenv file was changed. The route authority reported
71 rows and 788 routes; exported OpenAPI contained
588 paths and 758 operations, with no legacy platform-plugin paths.

This local production deployment explicitly required `python-api-v2`; it reached
globally ready at `2026-09-06T18:31:03.280441Z`, generation 1, requested version 1,
publication `578bcf5d-acb9-4477-b0a4-7de3e719a901`, snapshot digest
`5d41c942e9299e8220d83bdea8e35527932653fd51e8682815e92a2c556f9ecf`.
This is the configured local roster, not evidence that additional planes sent ACKs
to this particular deployment. The separate real three-plane integration above
exercises the required multi-plane behavior.

The existing local admin login succeeded, and the authenticated old plugin API
returned HTTP 410 with `plugin_protocol_v1_retired`. No platform-superuser record
exists in this database, so V2 administrative readiness endpoints correctly returned
403 for that account. No privileges were changed. Operational readiness evidence
comes from the exact persisted ROOT publication exported by the offline preflight,
not from falsely reporting those HTTP responses as 200.

The first startup exposed destructive provider recreation on credential verification
failure. It was stopped, the verified historical database backup was restored, and
the initializer was fixed in `0e88f8bbb`. The successful second startup and final
retirement retained all three original provider identities and encrypted credentials.
The incident, recovery and isolated regression are recorded separately in
[provider startup preservation](cordis-v2-provider-startup-preservation-2026-09-07.md).
The launcher resolved the existing container database password without changing the
endpoint, user or database, and supplied the original workspace encryption key only
in child-process memory. Repository dotenv files and database passwords are unchanged.

## Completed offline retirement

Before apply, the real CLI produced a fresh custom PostgreSQL backup, frozen V1
export and exact globally-ready ROOT snapshot under a bound preflight manifest:

| Artifact | Identity |
| --- | --- |
| Migration | `cordis-v2-final-retirement-20260907` |
| Preflight manifest digest | `sha256:a3e1775a8c6ca337930ba8234381ad57f9295af17eef1e68673ddfa730d367b2` |
| Database backup | 3,483,681 bytes; `sha256:8d160ab575b67c32017158317b8014ad614ea3422a8cc3ac9543a09e76e2efa7` |
| Conversion audit record | `48037c54-3ccb-4678-9543-0238b50c7b9b` |
| Operator identity | `codex:cordis-v2-final-retirement` |
| Retirement audit digest | `sha256:1d21067d426fc9563d7884a525c50f4aed140accb409423414c60c35d2bab2ce` |

The original database contained **zero V1 desired-state rows**. The successful plan
and apply therefore preserve ROOT revision 1 and its desired digest, and append
one audit record. No semantic conversion decisions were invented. The initialized
ROOT ProfileSource remains intact; its exact validation fix is documented in
[persisted-source retirement](cordis-v2-retirement-persisted-profile-source-2026-09-07.md).

Actual apply and an identical repeated apply both exited zero and returned identical
audit content. Read-only database checks after each verified exactly one conversion
audit, the unchanged ROOT desired head and ready snapshot, and all three original
providers unchanged. V1 runtime APIs remain tombstones; no compatibility fallback,
continuous dual write or runtime conversion bridge was introduced.

The fresh preflight backup restores the database to immediately before this audit.
The separate verified historical backup at revision `822cd9402ce6` remains available
for full old-version recovery with the matching previous deployment. Recovery uses
backup restoration and an appropriate prior version, not a fallback in this code.

## Final runtime correction and explicit V2 upgrade

The first shutdown exposed an APScheduler AnyIO context being entered and exited in
different tasks. `dc7a3a003` moved both into the same owned lifecycle task. Faster
startup then exposed SkillEvolution attempting an operation before installation of
the process ROOT host. `ac0420733` stages that consumer paused and activates it only
after the exact ROOT publication receipt is durable and admission is open. Initial
activation, HMR, receipt retry and supersession use the same fail-closed hook.
See [scheduler ownership](cordis-v2-scheduler-task-ownership-2026-09-07.md) and
[background activation](cordis-v2-background-publication-activation-2026-09-07.md).

Because this fix changes a manifest-bound Python artifact, its deployment was an
explicit subsequent V2 desired-set upgrade, separate from the completed V1 audit.
A read-only plan verified all 436 entries and the stored ProfileSource unchanged,
with only the approved SkillEvolution artifact changed. A new preflight backup was
created after the plan. The standard desired-set repository then performed the
revision-1 CAS and appended revision 2 under actor
`codex:cordis-v2-background-activation`. No historic row or privilege was rewritten.

| Final V2 rollout identity | Value |
| --- | --- |
| Plan content hash | `sha256:80922e540872dda4271ab750cbafbe83038d4e6ad8bcbf2b765269b7837709a3` |
| Fresh backup manifest content hash | `sha256:03d8053c4158ccb3c877778e7ced6803a1462c8228901a15e50ffc5f4013171a` |
| ROOT desired revision | 2 |
| ROOT desired digest | `sha256:de6d202a94cc866a237f6c4dca072771e69720c107a6db1a4e42c31db5287a3a` |
| Ready publication | `a788a9fa-8989-40b4-b893-6e6d58c19923` |
| Generation / snapshot | 2 / `d7847f3ec3089ae43c0401a2518c502af6dbf410289ac126bcba5ad10457540c` |
| Required planes | Exact `python-api-v2` ACK; publication status `ready` |

The post-activation real startup completed at 03:35:04 on September 7 (Asia/Shanghai). Its
initial skill-evolution cycle completed normally. Shutdown completed at 03:36:04,
including both schedulers, channel workers, retrieval, graph and telemetry disposers.
The final log contains no traceback, cancellation failure or missing process host.
Read-only repeatable-read checks before and after shutdown verified the exact new
publication, unchanged three Provider ciphertext identities, one original V1 audit,
preserved ProfileSource, and the complete original generation-1 ready snapshot.
Earlier failed runtime logs remain available and are not counted as passing.

## Final plan audit and DI retirement

The final stage-by-stage source check found no production references to
`AgentPluginRegistry`, `PluginRuntimeApi`, `LegacyInventoryBridge` or
`legacy-http-route-bridge`, and confirmed generation-owned route/navigation
projection. It also found the last three Agent business facades in DIContainer;
this omission was fixed rather than treated as a documentation exception.

`2b6424699` removes these facades and top-level AgentContainer assembly, moves
Workspace Provider/recovery repositories behind existing declared V2 factories and
full-duration leases, and deletes the implementations after unconditional legacy
worker/retry retirement errors. See [final DI retirement](cordis-v2-final-di-retirement-2026-09-07.md).
The source change preserves the generation-2 Bundle and its existing publication.

The final real rerun at this commit completed startup at 03:50:49 and shutdown at
03:51:20 on September 7 (Asia/Shanghai). The initial skill cycle, Neo4j connection
and every observed lifecycle disposer completed without an error traceback. The
existing admin authenticated successfully; the old plugin endpoint again returned
410 and OpenAPI retained 588 paths with no legacy plugin endpoint. Exact database
checks before and after shutdown again preserved ROOT revision 2, the ready
publication and required ACK, three Provider ciphertext identities, one V1 audit,
ProfileSource and the complete historic generation-1 snapshot. These final records
are separate from the earlier successful and failed runs.

## Evidence and final local state

Private evidence directories retain restrictive permissions and hash indexes:

- `/var/tmp/cordis-final-gates-p77rqmlc`: regression logs and `SHA256SUMS`.
- `/var/tmp/cordis-final-native-7TENNl`: original native operation screenshots,
  accessibility captures and manifest; no credential values.
- `/var/tmp/cordis-native-final-ac0420733`: final rebuild/restart persistence captures
  and manifest, separately bound to native artifact commit `ac0420733`.
- `/var/tmp/cordis-final-retirement-ufhyv7hu`: backup/export/snapshot, failed and
  successful plan logs, identical apply audits, read-only preservation checks,
  actual OpenAPI, runtime logs and `SHA256SUMS`.
- `/var/tmp/cordis-v1-backup-restore-h5nulhe6`: verified original historical backup.

After verification, the task-owned API/Core processes exited cleanly and ports
8000/4319 closed. The originally stopped PostgreSQL, Redis and Neo4j containers were
returned to their stopped state. `final-di-clean-lifecycle.json` and
`final-cleanup-2b6424699.json` record these checks. The native QA client and its
isolated profile remain available for inspection.
