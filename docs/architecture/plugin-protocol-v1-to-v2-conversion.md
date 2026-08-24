# Plugin Protocol V1 to V2 Desired-State Conversion

This runbook covers the single offline conversion from frozen protocol-v1 desired-state rows to
protocol-v2 `DesiredBundleSetV2` heads. It is not a runtime compatibility bridge and does not write
back to V1.

## Preconditions

- V1 mutation endpoints return `plugin_protocol_v1_mutation_frozen`.
- The database is migrated through revision `b5e9f3d8c012`.
- Every target V2 Bundle is installed, not revoked, scan-passed, signed, and has provenance.
- At least one immutable V2 publication has historically reached globally-ready.
- `pg_dump` and `pg_restore` are installed and compatible with the production PostgreSQL server.
- The conversion is run while application writers are stopped or otherwise excluded.

Never place credentials or raw V1 configuration values in the mapping. The export contains only
configuration key names and canonical digests.

## Offline workflow

Choose a unique migration ID and a private output directory that does not already exist. First create
the mandatory recovery bundle:

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py preflight \
  --migration-id plugin-v1-final-YYYYMMDD \
  --output-dir /secure/audit/plugin-v1-final-YYYYMMDD
```

The command fails closed unless it can create and validate all of these artifacts:

- `database.backup`: a PostgreSQL custom-format archive validated by `pg_restore --list`;
- `plugin-v1-export.json`: the exact secret-free V1 source and V2 target-head template;
- `last-ready-v2-snapshot.json`: the exact persisted publication that historically reached
  globally-ready;
- `preflight-manifest.json`: canonical sizes and SHA-256 digests binding all three artifacts to the
  migration ID, V1 source digest, publication nonce, requested version, and snapshot digest.

The directory is created with mode `0700`; files use `0600`; temporary output is removed on failure;
existing output is never overwritten. The database password is passed to `pg_dump` only through its
process environment and is never placed in command arguments, reports, or manifests.

Copy `plugin-v1-export.json` to a new review path and fill in its decisions. The standalone `export`
subcommand remains available for diagnostics, but its output is not accepted as retirement safety
evidence without the matching preflight manifest.

For every exported row, an agent must produce one structured decision with an exact action and, when
required, an exact Bundle reference. The recorded judgment must include `agent_id`, `tool_name`,
`input_digest`, `output_digest`, `rationale`, and `latency_ms`. Do not infer a Bundle from a V1 name,
keyword, or configuration value.

Validate the reviewed mapping without writes:

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py plan \
  --mapping /secure/audit/plugin-v1-reviewed.json \
  --preflight-manifest \
    /secure/audit/plugin-v1-final-YYYYMMDD/preflight-manifest.json \
  --output /secure/audit/plugin-v1-plan.json
```

Apply only after reviewing the source digest, target heads, decisions, and plan. The confirmation must
exactly match the mapping's migration ID:

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py apply \
  --mapping /secure/audit/plugin-v1-reviewed.json \
  --actor-id platform-admin \
  --confirm-migration-id plugin-v1-final-YYYYMMDD \
  --preflight-manifest \
    /secure/audit/plugin-v1-final-YYYYMMDD/preflight-manifest.json \
  --output /secure/audit/plugin-v1-result.json
```

Both `plan` and `apply` re-hash every recovery artifact, validate the PostgreSQL archive, bind the
saved V1 export to the reviewed mapping, and compare the saved globally-ready snapshot with the exact
persisted publication nonce before any V2 write. `apply` atomically appends changed V2 desired-set
heads and one immutable database audit record. Its private result file additionally binds the
conversion report to the preflight manifest and all recovery artifact digests through one
`audit_digest`. It retains all V1 rows. Reapplying byte-equivalent evidence is idempotent; reusing the
migration ID with different source or mapping evidence fails with `migration_id_conflict`.

## Failure and rollback

Source drift, target-head drift, missing judgments, malformed scopes, unavailable Bundles, or an
untrusted Bundle fail before commit. A failed transaction leaves both the current V2 heads and V1
rows unchanged.

This conversion alone does not authorize V1 deletion. Until full V2 composition evidence,
Web/Desktop parity, and native provider QA all pass, rollback is a new V2 publication of the saved
globally-ready snapshot. Destructive V1 retirement requires the preflight database backup, the
pre-retirement application version, and the complete result audit file.
