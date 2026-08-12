# Avernet BCS upstream record

This directory vendors the complete `src/bcs` tree from Avernet as the fixed
collaboration-kernel baseline for the MemStack Workspace Core migration.

| Field | Value |
| --- | --- |
| Upstream repository | `https://github.com/inclusionAI/Avernet` |
| Upstream commit | `e470fb3d88979b9da8dc11c63f9d9c4b73343c9d` |
| Upstream tree | `a5f7da1ab934cee9d2e8e2156605c2632e2c6b12` (`src/bcs`) |
| Imported on | 2026-08-10 |
| Root license | Apache-2.0; see `LICENSE` |
| Update policy | Deliberate reviewed imports only; no automatic upstream merge |

`UPSTREAM_MANIFEST.sha256` contains one checksum for every file imported from
`src/bcs`, plus the upstream root `LICENSE`. `UPSTREAM_TREE.tsv` records the
corresponding Git path, blob, and executable mode. These two files always
describe the unmodified fixed upstream baseline. Run:

```bash
make -C third_party/avernet-bcs verify-import
```

before and after any upstream refresh. A refresh must update the commit, tree,
manifest, license review, dependency audit, and migration compatibility report
in one isolated change.

## Downstream patch ledger

MemStack compatibility changes to an imported file must be registered in
`DOWNSTREAM_PATCHES.tsv`. Each non-comment line contains four tab-separated
fields:

```text
path<TAB>upstream_sha256<TAB>local_sha256<TAB>reason
```

The upstream checksum must match the same path in
`UPSTREAM_MANIFEST.sha256`; the local checksum must match the working-tree
file; and the reason must identify the compatibility need. The verifier
rejects unknown paths, duplicate or stale entries, incorrect modes, local
hash drift, and any modification to an imported file that is not registered.
Do not rewrite the upstream manifests when adding a downstream patch.

## MemStack-owned integration files

The following files were added by MemStack and are not part of the recorded
upstream tree:

- `UPSTREAM.md`
- `UPSTREAM_MANIFEST.sha256`
- `UPSTREAM_TREE.tsv`
- `DOWNSTREAM_PATCHES.tsv`
- `DOWNSTREAM_ADDITIONS.tsv`
- `license-policy.json`
- `rust-toolchain.toml`
- `Makefile`

Production changes to imported BCS files must carry an explicit ledger entry
and must not be mixed with a later upstream refresh. Run
`scripts/avernet-bcs/test-verify-import.sh` after changing verifier policy.

## License review status

The Avernet repository root supplies Apache-2.0. Two imported package manifests
declare MIT independently:

- `crates/plugins/bcs-storage-baas/Cargo.toml`
- `crates/plugins/openclaw-channel-bcn/package.json`

The fixed imported tree did not include an MIT license text or package-level
copyright notice for either declaration. MemStack supplies an adjacent
`LICENSE` and source-specific `NOTICE` for both packages and records those files
in `DOWNSTREAM_ADDITIONS.tsv`. The notices identify this upstream repository,
revision, and package path without expanding the manifest's license grant.

`license-policy.json` freezes the reviewed Cargo and npm license expressions,
the complete npm lockfile set, and the one explicitly classified local test
fixture. `scripts/avernet-bcs/test-supply-chain.sh` fails if a package manifest
is not locked or explicitly classified, if a required notice disappears, or if
the deterministic Cargo/npm CycloneDX inventories drift between identical
inputs. `scripts/avernet-bcs/audit.sh` pins cargo-audit 0.22.2 and denies all
vulnerability, unmaintained, unsound, and yanked findings without an advisory
allowlist.

## Reproducible build provenance

The two BCS build scripts never inspect the enclosing Git worktree or local
clock. They embed the fixed Avernet upstream revision separately from the
caller-supplied `MEMSTACK_HOST_GIT_REVISION`; `BUILD_DATE` is derived only from
`SOURCE_DATE_EPOCH` in UTC. Release and CI builds must provide both controlled
inputs. A missing host revision or epoch produces the deterministic value
`unknown`, while a malformed epoch fails the build.
