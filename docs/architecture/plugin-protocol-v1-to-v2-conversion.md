# Plugin Protocol V1 to V2 Desired-State Conversion

This runbook covers the single offline conversion from frozen protocol-v1 desired-state rows to
protocol-v2 `DesiredBundleSetV2` heads. It is not a runtime compatibility bridge and does not write
back to V1.

## Preconditions

- V1 mutation endpoints return `plugin_protocol_v1_mutation_frozen`.
- The database is migrated through revision `b5e9f3d8c012`.
- Every target V2 Bundle is installed, not revoked, scan-passed, signed, and has provenance.
- The operator has a database backup, a V1 export, and the last globally-ready V2 snapshot.
- The conversion is run while application writers are stopped or otherwise excluded.

Never place credentials or raw V1 configuration values in the mapping. The export contains only
configuration key names and canonical digests.

## Offline workflow

Choose a unique migration ID and output paths that do not already exist. The CLI creates outputs
with mode `0600` and refuses to overwrite them.

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py export \
  --migration-id plugin-v1-final-YYYYMMDD \
  --output /secure/audit/plugin-v1-export.json
```

For every exported row, an agent must produce one structured decision with an exact action and, when
required, an exact Bundle reference. The recorded judgment must include `agent_id`, `tool_name`,
`input_digest`, `output_digest`, `rationale`, and `latency_ms`. Do not infer a Bundle from a V1 name,
keyword, or configuration value.

Validate the reviewed mapping without writes:

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py plan \
  --mapping /secure/audit/plugin-v1-reviewed.json \
  --output /secure/audit/plugin-v1-plan.json
```

Apply only after reviewing the source digest, target heads, decisions, and plan. The confirmation must
exactly match the mapping's migration ID:

```bash
uv run python scripts/migrate_plugin_protocol_v1_to_v2.py apply \
  --mapping /secure/audit/plugin-v1-reviewed.json \
  --actor-id platform-admin \
  --confirm-migration-id plugin-v1-final-YYYYMMDD \
  --output /secure/audit/plugin-v1-result.json
```

`apply` atomically appends changed V2 desired-set heads and one immutable audit record. It retains all
V1 rows. Reapplying byte-equivalent evidence is idempotent; reusing the migration ID with different
source or mapping evidence fails with `migration_id_conflict`.

## Failure and rollback

Source drift, target-head drift, missing judgments, malformed scopes, unavailable Bundles, or an
untrusted Bundle fail before commit. A failed transaction leaves both the current V2 heads and V1
rows unchanged.

This conversion alone does not authorize V1 deletion. Until full V2 composition evidence, a globally
ready publication, Web/Desktop parity, and native provider QA all pass, rollback is a new V2
publication of the previous globally-ready snapshot. Destructive V1 retirement requires the saved
database backup and the pre-retirement application version.
