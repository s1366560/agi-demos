# Desktop Client Test Baseline Report

Date: 2026-09-10 (session) · Repo: `/Users/tiejunsun/github/agi-demos` · Scope: `make -C agi-stack desktop-check` steps 1–5, run individually, no fixes applied.

## Environment

- **Free disk space**: 161 Gi available (736 Gi / 926 Gi used, 83%) on `/dev/disk3s5` — observed before and after the run (unchanged; all builds were incremental).
- pnpm 11.15.1 (`/usr/local/bin/pnpm`); `node_modules` already present in `agi-stack/apps/desktop` (`desktop-deps` install step not needed).
- Makefile `$(CARGO)` resolves to plain `cargo` with `$(HOME)/.cargo/bin` prepended to `PATH`; sidecar build/test run in the `agi-stack/` Cargo workspace (member `apps/desktop/sidecar`).
- workspace-core is built via the canonical wrapper `scripts/avernet-bcs/cargo.sh` (isolated rustup toolchain 1.91.1 + protoc 25.3, `CARGO_TARGET_DIR=$AVERNET_BCS_TARGET_DIR`), invoked by `apps/desktop/scripts/build-workspace-core.mjs`.
- `AVERNET_BCS_TARGET_DIR = /Users/tiejunsun/github/agi-demos/.cache/avernet-bcs/target`
- `DESKTOP_WORKSPACE_CORE_DEBUG = /Users/tiejunsun/github/agi-demos/.cache/avernet-bcs/target/debug/memstack-workspace-core` (present, 141,928,072 bytes)
- Sidecar binary: `/Users/tiejunsun/github/agi-demos/agi-stack/target/debug/agistack-desktop-sidecar` (present, 91,517,128 bytes)
- Note: both Rust binaries were already compiled (artifact timestamps Sep 10 16:54); steps 1–2 were no-op incremental builds (~1 s each). A cold-build baseline was therefore not measured.

## Step results

| # | Step | Result | Duration | Details |
|---|------|--------|----------|---------|
| 1 | `pnpm run build:workspace-core:debug` | **PASS** | ~1 s | `Finished dev profile [unoptimized + debuginfo] in 1.05s` (fully cached). Log: `1-workspace-core.log` |
| 2 | `cargo build -p agistack-desktop-sidecar` (in `agi-stack/`) | **PASS** | ~1 s | `Finished dev profile in 1.02s` (fully cached). Log: `2-sidecar-build.log` |
| 3 | `cargo test -p agistack-desktop-sidecar` | **PASS** | 25 s | 863 tests: **862 passed, 0 failed, 1 ignored**, 23.73 s test time. Log: `3-sidecar-test.log` |
| 4 | `pnpm test` with `AGISTACK_REAL_SIDECAR` + `AGISTACK_REAL_WORKSPACE_CORE` | **PASS** | 284 s wall (compile ~268 s + 16 s tests) | **4589 tests: 4588 passed, 0 failed, 1 skipped**, 0 cancelled. Log: `4-renderer-test.log` |
| 5 | `pnpm run build:electron` (tsc ×2 + electron-vite build) | **PASS** | 20 s | Both `tsc --noEmit` passes clean; electron-vite built main/preload/renderer, `✓ built in 9.42s`. Log: `5-electron-build.log` |

## Step 4 detail

- **Failing test files: none.** Zero `not ok` lines in the TAP output, so there is no failing-file list to group by area (chat/workspace/skills/plugins/tools/agent/subagent/other all green).
- Totals: tests 4589 · suites 0 · pass 4588 · fail 0 · cancelled 0 · skipped 1 · todo 0 · duration_ms 15959.
- The single skipped test is not individually identifiable from the TAP summary (no per-file skip annotation surfaced); it is an intentional `skip` in the suite, not an environmental skip.
- Runner mechanics: `tests/run.mjs` wipes and recompiles `/tmp/agistack-desktop-test-dist` (plus three `project-*` tsconfigs) on every invocation and does **not** support test-file filtering — re-runs are full runs; the compile phase dominates wall time.

## Environmental blockers

None encountered. pnpm store/deps present, both Rust toolchains ready, no network installs required, no timeouts (each step fit within the 300 s foreground cap; step 4 was run as a detached process and polled to completion, 284 s total).

## Conclusion

Full `desktop-check` baseline is **green end-to-end**: workspace-core builds, sidecar builds and passes 862/863 tests (1 ignored), the ~4.6k renderer/node test suite (including real-sidecar integration against the two env-pinned binaries) passes with zero failures, and the Electron production build (type-check + electron-vite) succeeds. Any future regression work can diff against the logs in `artifacts/desktop-baseline/`.
