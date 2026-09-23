# Runtime Instances: review of four pre-merge untracked files

## Decision

Reviewed against main `fd6dc8adb` on 2026-09-07. All four paths are already
tracked: their accepted implementations entered history in `2f189fd68` and
reached main through `c18194581`. The preserved untracked variants are older,
incompatible drafts. Keep the current implementations; do not overwrite them
or add a second copy of obsolete executable code. This commit records the
review, not four new runtime implementations.

Original bytes remain in `/var/tmp/cordis-main-merge-backup-6_6tq9dq`, under
the paths below. All four SHA-256 values were verified against its manifest.
This local backup is not a portable Git archive.

## File decisions

| File | Backup difference | Decision |
| --- | --- | --- |
| `runtimeInstancesContract.ts` | Advertises `inspect-health` and current-page search/filter; lacks local actions. | Keep current local actions and cloud lifecycle contract. |
| `desktopRuntimeInstancesAuthorityModuleV2.ts` | Exposes `getHealth` instead of `restart` and `delete`; imports removed `RuntimeInstanceHealth`. | Keep the current authority/client interface; restoring the draft breaks current consumers. |
| `desktopRuntimeInstancesHttpProjectionV2.ts` | Requires cluster-shaped fields, requests instance `/health`, and rejects local listing. | Keep the current instance schema and native sidecar projection. |
| `desktopRuntimeInstancesOperationContractV2.ts` | Validates cluster/health results and a `health` operation; lacks current mutation and projection contracts. | Keep current validation consistent with current types and authority. |

The shared generation admission, operation leasing, scope checks, cloning,
and error boundaries are already present in current code. No independent
backup-only fix was identified in the complete four-file diffs.

## Interface evidence and limits

- `agi-stack/apps/desktop/src/features/runtime-instances/runtimeInstancesTypes.ts`
  defines instance replica/image/cluster/projection fields and list/restart/delete.
  It does not export the backup's `RuntimeInstanceHealth`.
- `src/application/schemas/instance_schemas.py` defines `InstanceResponse` with
  image, replica and cluster fields. The backup requires `proxy_endpoint` and
  `last_health_check`, which are not fields of that response.
- `src/application/schemas/cluster_schemas.py` defines the node count, CPU,
  memory and checked-at health shape used by the backup. Its route is under
  clusters in `src/infrastructure/adapters/primary/web/routers/clusters.py`.
  The instance routers in Python and Rust do not expose the backup's instance
  `/health` route. Python does expose instance restart and deletion.
- Current Desktop sends cloud `search` and `status` parameters, but Python
  `list_instances` and Rust `InstanceListQuery` currently accept only page and
  page size. Request-construction tests do not establish server filtering.
  This is an existing limitation, not a reason to restore the incompatible
  drafts. End-to-end cloud filtering is not accepted by this review.
- No runtime symbols or parity evidence are changed. This review does not
  represent new native, live-cloud, or full-feature acceptance.

## Backup inventory

- `agi-stack/apps/desktop/src/features/runtime-instances/runtimeInstancesContract.ts`
  SHA-256: `ed53fb06f051cae03c55f4022b4fc7d664577e4bf4f127cd26ac8ca89b613abe`
- `agi-stack/apps/desktop/src/plugins/desktopRuntimeInstancesAuthorityModuleV2.ts`
  SHA-256: `deedf93162dbe37bf823f922b7ab0434e12de65ab7d41a67671dec22009636da`
- `agi-stack/apps/desktop/src/plugins/desktopRuntimeInstancesHttpProjectionV2.ts`
  SHA-256: `1b451ff0b6280faa4580b08da241dea78e449feed6a284f87ee7819c98cff3ae`
- `agi-stack/apps/desktop/src/plugins/desktopRuntimeInstancesOperationContractV2.ts`
  SHA-256: `b0617e5a93d04dc613c7772a7e4b5e2dd3611df3e3e908ce5fb28dc683e8683b`

## Validation

- `pnpm test` in `agi-stack/apps/desktop` at reviewed main: TypeScript test
  compilation succeeded; 4,131 passed, two skipped, zero failed out of 4,133
  tests (109,211 ms). Log: `/tmp/cordis-four-files-evaluation-tests.log`.
- Backup manifest: four of four SHA-256 checks passed.
- Git scope review confirms this is a documentation-only addition; runtime
  source and parity artifacts remain unchanged.
