# Cordis V2 exact scoped restart restore

Application scoped acquisition now recovers a previously admitted, source-bound session when this process has no local admission. It reads the retained publication and freshly loads its exact historical Bundle references through the configured verified loader. It does not initialize configuration, compose current desired, allocate a publication version or append a receipt.

The recovery repository reads under the scope-head lock. It validates the complete stored distribution and row identities, required data-plane membership, actual receipt requested/applied references and the retained publication source binding. A newer request without its own receipt is explicitly distinguished from an earlier ACK, including the same-version/new-nonce case. A latest persisted NACK can retain the prior ACK; it is not replaced with a synthetic successful receipt.

The coordinator compares the complete recovery state before staging and again after real Loader staging. Only a local ACK for the exact retained snapshot/envelope opens admission. The latest persisted receipt supplies the observed identity used by subsequent normal durable admission checks. State changes during staging, local NACK, missing lineage or invalid archives leave acquisition unavailable. Owned restore work and scope shutdown retain cleanup responsibility when the caller cancels.

Control and recovery consumers recheck SQL authorization after acquisition, because recovery may await archive IO. Revocation during that interval releases the newly obtained lease. The existing targeted HITL authorization remains in use.

## Scope and remaining work

This restores publications with explicit source bindings; it does not guess historical lineage for older unbound rows. Unreceipted requests still need explicit reconciliation. Fresh archive validation is not a continuous governance/revocation fence. Active processes whose existing publication becomes stale do not silently rebind existing operations. Historical migration-chain recovery, ROOT lineage/migration, broader actor/worker coverage, PostgreSQL restore-vs-publication concurrency acceptance, final V1 retirement, parity rebinding and native acceptance remain open.

Tests use real SQL persistence and real signed archive/Loader generations with two independent coordinator instances. They do not constitute a live marketplace, Redis, model, or native desktop acceptance run.

## Validation

- Recovery, repository and startup/coordinator regression: 30 passed, 21 warnings, 37.94 seconds.
- WebSocket full directory: 157 passed, 21 warnings, 55.83 seconds.
- Focused revocation/control run: 25 passed, included in the directory run.
- Pyright 0 errors/0 warnings; Ruff and protocol generation/completeness checks passed.
- Logs and SHA256SUMS: `/var/tmp/cordis-scoped-restore-up98u6v5`.
