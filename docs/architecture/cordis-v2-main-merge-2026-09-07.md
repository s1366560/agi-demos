# Cordis V2 integration into main

Merge commit `c181945815fb5d6617b21046bb88301110130d2f` combines main
`760d55ec8524ca116f17e50f08a9e49ced13a42d` and the completed Cordis branch
`7d666d99971f96fa6d94c539b0a39bb081768312`. Both histories are retained.

## Merge resolutions

- Kept the V2 VNC view/controller boundary and main's cancellable deferred RFB
  connection. StrictMode creates one physical socket, and an early unmount creates
  none; disposal and generation draining remain intact.
- Removed the retired V1 mutation ledger, whose previous contents remain in the
  main parent commit. Kept the Cordis repository instructions.
- Corrected a semantic conflict in automatically merged project deletion: main's
  sandbox resource purge now uses the request-pinned V2 sandbox authority instead
  of the removed DI accessor. Authorization, scope locking and failure-before-commit
  behavior are preserved for both project and tenant deletion.
- Preserved main's Rust shared-memory/seccomp/named-volume ownership behavior along
  with the Cordis runtime and typed tool contracts.

Four pre-existing untracked runtime-instance files overlapped committed Cordis
files and differed from them. They were copied with checksum verification to
`/var/tmp/cordis-main-merge-backup-6_6tq9dq` before merge. The merged checkout uses
Cordis's committed versions; the original untracked variants remain recoverable
with their path/hash manifest and were not silently committed over the accepted code.

## Validation boundaries

- VNC: 23 focused tests, TypeScript, formatting and zero ESLint errors.
- Sandbox Python: 73 tests passed.
- Project/tenant deletion: 11 tests passed, Ruff passed, Pyright zero errors.
- Rust: five affected crates passed all-targets checking; workspace formatting passed.
  Core 63, memory adapters 43, Docker adapter 2, server 613 and sidecar 640 unit tests
  passed, totaling 1,361. Docker daemon integration tests were compiled, not executed.
- Protocol generation consistency and contract completeness checks passed.
- Merge pre-commit: 649-file Python type check and all required hooks passed;
  ESLint retained warnings with zero errors. The staged secret scan found no leaks.
- The first pre-commit Desktop run had two failures because its committed HEAD was
  still the old main: one contract-content binding and one source-ancestor check.
  This preliminary run is retained as failed evidence, not counted as acceptance.

The main GitNexus index could not open its existing pending WAL during scope checks.
The failure was retained; it is not reported as a successful graph analysis. Conflict
scope was inspected through parent and staged Git diffs, with targeted regression
and compile checks. The VNC graph analysis against the available Cordis index
reported HIGH risk and was disclosed before editing.

Parity commit `93f7deb38` binds the actual merge source commit while retaining
all capability states and `source_content_integrity_only`/`execution_evidence: false`.
It verified 887 source proofs and 25 BrowserBridge proofs; 82 focused tests and all
four canonical inventory/V2/V3/V4 checks passed. Its private evidence is retained in
`/var/tmp/cordis-parity-main-merge-c18194581`.
The final complete Desktop run on `93f7deb38` passed: **4,131 passed, two skipped,
zero failed** (4,133 tests). Both preliminary HEAD-binding failures passed after
the merge and parity commits. This final documentation-only commit does not change
the tested runtime or contract files.

Evidence logs are retained under `/var/tmp/cordis-main-merge-evidence-qv6n34qa`.
