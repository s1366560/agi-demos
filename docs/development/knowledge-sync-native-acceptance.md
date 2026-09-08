# Explicit native and cloud knowledge sync acceptance

The ordinary desktop release remains closed. The existing
`memstack-local-knowledge-acceptance-v2` profile remains local only. Temporary QA
roots alone do not grant synchronization.

A joint QA run uses two independent fixed profiles:

| Host | Profile | Changes from the default profile |
| --- | --- | --- |
| Native Electron | `memstack-knowledge-sync-acceptance-v2` | Enables only the native knowledge authority with `knowledge-sync-acceptance-v1` purpose |
| Cloud | `memstack-cloud-knowledge-sync-acceptance-v2` | Enables only the three cloud knowledge sync repository, application and HTTP route entries |

For the native leg, launch the canonical repository Make target with
`AGISTACK_DESKTOP_QA_PURPOSE=knowledge-sync-acceptance-v1` and the existing isolated
QA profile and workspace settings. Both directories must be distinct direct
children of the platform temporary directory with the `agistack-desktop-qa-`
prefix. Launch with `make -C agi-stack run-desktop` from the repository root.

Electron rejects packaged builds and missing isolated roots before it creates the
request. It sends the fixed purpose, `isPackaged: false`, and bound user-data path
through the authenticated private sidecar initialization pipe. Rust accepts this
qualification only in debug builds and independently checks temporary location,
0700 permissions, directory identity, ownership consistency, and the bound runtime
child. Later scope, storage and sync checks repeat directory validation; replacing
an inode or changing permissions revokes the qualification.

The native fixed snapshot and digest must match the host purpose. A cloud
publication cannot replace this local host qualification. The connector must call
`require_sync_cloud_profile` with the actual authenticated cloud enrollment
profile, generation and digest before binding or sending synchronization traffic.
It must also fence authenticated connection state and the exact durable target;
the QA profile does not supply credentials, target selection or enrollment.

The cloud snapshot is a compiled qualification template, not a constant runtime
digest. Protocol snapshot digests include generation. The native checker validates
the compiled cloud template, replaces only its generation with the observed
positive protocol integer, and computes the standard canonical JSON SHA256. It
compares that expected digest and fixed cloud profile ID with the observed
descriptor. The request generation header continues to carry the actual observed
descriptor. Generated Python/Rust vectors cover generations 1, 81 and 82.

Regenerate profiles and vectors with `scripts/generate_plugin_protocol_v2.py`.
After source changes, refresh only the reviewed module artifacts through the
script's `--refresh-artifacts` option, then run its `--check`. A regenerated template
requires rebuilding the native binary before comparison with the cloud profile.
No default entry is enabled by generating these QA artifacts.
