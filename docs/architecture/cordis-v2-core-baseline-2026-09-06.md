# Cordis V2 cross-batch Python baseline

Command: `PYTHONPATH=. uv run pytest src/tests/unit/infrastructure/plugins/v2 -q`.

The completed run collected 1607 cases: **1605 passed, 2 failed, 21 warnings**, 2054.40 seconds. Evidence and SHA256SUMS: `/var/tmp/cordis-v2-core-baseline-7awcojhp`.

The run began before the subsequent ROOT execution/startup batches and continued while the workspace changed. It is useful broad regression evidence, not a fixed final-revision acceptance gate, and it must not be reported as a passing full suite.

## Failures and required correction

Both failures are in `test_agent_pool_runtime_v2.py`.

- The explicit-pool-desired restart test only passed startup flags after an initial persistent startup. It did not update saved desired/source. ROOT initialization now preserves existing configuration, so generation correctly stayed unchanged. The test must persist the requested pool configuration through the source and desired repositories before expecting a new generation.
- The pre-pool snapshot test persisted legacy runtime history with no desired/source configuration and expected implicit upgrade. Persistent ROOT startup requires explicit migration for that state. The test must check the migration-required failure and preservation of the existing ledger; it must not restore the removed default-overlay behavior.

These corrections do not complete legacy migration. An explicit, verified migration path and a final frozen-revision full run remain outstanding.

## Focused correction result

Both obsolete setup/expectation paths were corrected without changing production behavior. The first test now persists a new source replacement and desired revision, then supplies a conflicting disabled startup flag to prove stored configuration wins and the Pool actually starts/stops. The second requires the migration error and checks that no desired/source rows appear and last-good/requested history stays unchanged.

The complete Agent Pool test file passes: **8 passed, 48.73 seconds**; Ruff and diff checks pass. Its log is saved alongside the baseline. This focused rerun resolves the two observed failures, but does not turn the earlier mixed-revision full run into a passing final gate.
