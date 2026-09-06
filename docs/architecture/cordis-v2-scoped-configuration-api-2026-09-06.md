# Scoped configuration API and explicit service closure

The production platform-plugin contribution now exposes POST
`/api/v1/platform-plugins/v2/profile-sources`. It accepts exactly `scope`, `source`
and `expected_revision`, authenticates the user, checks persisted resource ancestry
and publication write permission, and stores an immutable source revision. Its
response reports the saved source, not an applied runtime or trusted executable.

The existing desired-set PUT now permits authorized non-ROOT scope writers only
when the exact source reference exists in the same scope. ROOT retains platform
administrator authorization and its baseline behavior. Source revisions may be
stored independently: a failed desired CAS leaves an unreferenced immutable source,
and does not change the current desired pointer. No external fetch is performed.
The desired repository locks ScopeHead before reading its current row, including
the first write, so competing initial CAS requests cannot both succeed.

The new Python service-closure projector takes explicit service requirements and
uses the same provider resolver as Loader ordering. It follows declared dependencies,
scope ancestry, versions, isolation and parent entries; rejects missing/ambiguous
providers, cycles and global route services; retains selected contracts/artifact
references; and recomputes the snapshot digest. It does not infer intent from names.

Validation: 73 combined router, service-closure, runtime and scope-lock regressions
passed. Twelve isolated PostgreSQL tests passed, including competing first desired
writes and preceding publication/source/receipt tests. The route artifact digest and
generated catalogs/bootstrap were regenerated from actual source bytes; only the
platform-plugins route module's artifact digest changed in the catalog.

The APIs save configuration only. The application still needs to resolve trusted
Bundle bytes, compose the saved source, project the complete consumer dependencies,
and call the scoped coordinator from production Agent boundaries. Startup ownership,
exact child leases, restart recovery, V1 retirement and final native acceptance remain
outstanding; this batch does not complete Stage 6.

Reproduction scripts and hashed logs: `/var/tmp/cordis-scoped-config-qb7vub50`.
