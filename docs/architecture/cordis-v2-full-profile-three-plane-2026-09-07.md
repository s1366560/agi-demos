# Cordis V2 full profile three-plane acceptance

The production Desktop renderer now exposes a factory used by its existing private
singleton and by the multi-plane integration runner. The ordered plugin definitions
and contribution validator are preserved. This allows the integration gate to apply
the complete production profile instead of assembling a reduced renderer fixture.

## Scope and observed behavior

The test starts the real Python runtime and publication repository on migrated,
isolated PostgreSQL, serves the delivery API over loopback HTTP, and starts the real
Desktop sidecar through `SidecarSupervisor`. Its renderer uses the production
factory. The test runner only stubs CSS loading for Node, following the existing
test compilation convention; it does not replace runtime authority or receipts.

The initial snapshot contains the same 436 entry IDs as the generated default
bootstrap profile. The deployment explicitly requires Python, Desktop sidecar and
Desktop renderer receipts with a finite 90-second deadline. All three acknowledge
the first publication, which becomes ready. Subsequent valid profile revisions
disable the sidecar HTTP routes provider and then the renderer contribution
registry. The affected real plane rejects each candidate; the other two acknowledge
it. Rejections preserve that plane's prior applied version and digest, and the
original globally ready publication retains its readiness timestamp.

The full profile also contains Rust server and Web entries. This test does not run
those planes or establish their deployment acceptance. The Node renderer runner is
not native Electron UI evidence; native acceptance is recorded separately.

## Validation at the change based on eee908c0d

- Full-profile HTTP/PostgreSQL integration: 1 passed, 23 warnings, 75.64 seconds;
  owned PostgreSQL cleanup exited 0.
  Log: `/tmp/cordis-full-profile-three-plane-final.log`.
- Renderer and delivery focused tests: 19 passed.
  Log: `/tmp/cordis-production-renderer-focused.log`.
- Production wiring focused tests: 192 passed.
  Log: `/tmp/cordis-production-wiring-focused.log`.
- Complete Desktop retry before committing: 4,130 passed, 1 failed, 2 skipped.
  The remaining failure is the existing parity generator's check that a reviewed
  source file matches its HEAD blob; the extracted hook is intentionally still
  uncommitted at this point. The guard remains intact. A post-commit full run is
  required before this batch's complete Desktop gate can be recorded as passing.
  Log: `/tmp/cordis-full-production-desktop-extract-retry2.log`.

Earlier attempts exposed missing moved imports, a fixture import removed during
linting, Node CSS loading, and wiring tests reading only the old assembly file.
Those defects were corrected before the focused and integration successes above.
Initial attempt logs were partly overwritten, so the retained final logs must not
be presented as an uninterrupted first-attempt success.

The factory preserves the singleton and definition ordering. Source-based
wiring tests now read both assembly files and assert the singleton uses the factory.
