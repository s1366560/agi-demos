# Explicit ROOT builtin bundle maintenance

Changing attested builtin source changes the production bundle digest. An existing
ROOT desired configuration continues to reference the previous exact bundle, so
startup correctly rejects it until an explicit maintenance upgrade is recorded.

Stop the API and validate the new source, artifact declarations, and generated
catalogs first. Inspect the stored reference without changing state:

```bash
uv run python scripts/upgrade_root_builtin_bundle_v2.py
```

Review the displayed old/new digests and desired revision, then use those exact
old values with an audit actor identifier:

```bash
uv run python scripts/upgrade_root_builtin_bundle_v2.py --apply \
  --expected-revision REVISION --expected-digest sha256:OLD_DIGEST \
  --actor-id MAINTENANCE_ACTOR
```

The application service verifies every candidate archive, checks composition,
preserves the exact ProfileSource and unrelated bundle references, and appends a
CAS desired revision through the existing repository. Errors before commit leave
the previous desired state intact. This is an explicit ROOT builtin maintenance
operation, not a marketplace install or automatic startup rebind.

Existing tenant, project, and session configurations retain their own exact
bundle references. Upgrade each affected scope explicitly using the same inspect
and expected-revision/digest procedure, adding `--scope-kind tenant|project|session`
and the corresponding `--tenant-id`, `--project-id`, and `--session-id` arguments.
Each operation preserves that scope's own ProfileSource and unrelated bundles;
it does not copy or overwrite them from ROOT.

If marketplace bundles are present, supply their configured trust policy using
repeated `--trusted-public-key` and `--allowed-registry` options. Missing trust
configuration fails closed. Restart the API normally so the regular verified
publication path activates the new revision; inspect startup and application
behavior before considering maintenance complete.
