# Development disk usage

Build caches must remain disposable and separate from application data. Use the
following commands from the repository root. The cleanup utility requires a
macOS or Linux host with Python 3, `lsof`, and `ps`:

| Command | Effect |
| --- | --- |
| `make disk-usage` | Report the known build-cache locations and allocated disk space; delete nothing. |
| `make clean-cache` | Remove idle Rust incremental caches. Keep compiled dependencies. |
| `make clean-build-cache` | Remove idle Rust dependency, build-script, fingerprint and incremental caches. The next build recompiles dependencies. |
| `make clean` | Clean Python/Web artifacts and incremental caches; retain logs and Docker data. |

The Rust cleanup tool uses an explicit list of build directories under
`agi-stack/target`, `.cache/avernet-bcs/target`, the historical
`third_party/avernet-bcs/target`, and the isolated Cargo audit build target.
It preserves binaries directly under `target/debug` and `target/release`.
Do not delete `.cache` or `.cache/avernet-bcs` as a whole: the latter can also
contain Workspace Core databases in `test-data`, compiler toolchains, and Cargo
downloads. Dependencies such as `node_modules` and `.venv`, Git data, logs, user
workspaces, and Docker volumes are outside this cleanup list.

The script defaults to a dry run. Direct destructive use requires both a group
and `--apply`, for example:

```bash
python3 scripts/dev_disk.py --group rust-incremental --apply
```

To remove only a particular workspace's caches, add `--target agi-stack`,
`--target workspace-core`, `--target legacy-workspace-core`, or `--target audit`.
For example, retire the old duplicate Workspace Core build without invalidating
the current caches:

```bash
python3 scripts/dev_disk.py --group rust-build --target legacy-workspace-core --apply
```

Cleanup rejects symlinks, mounted artifact directories, tracked files and occupied
build paths. It also checks for compilers running outside Cargo and holds Cargo's
profile `.cargo-lock` exclusively
through deletion. This coordinates with both the older exclusive lock and
[Cargo's newer shared compatibility lock](https://github.com/rust-lang/cargo/pull/16887).
The lock file is preserved. If a build holds the lock or occupancy inspection is
unavailable, cleanup refuses deletion. Finish builds before applying cleanup;
arbitrary non-Cargo writers do not necessarily participate in Cargo's lock.
Custom target locations are not discovered or deleted automatically.

`make clean-docker`, `make clean-logs` and `make reset` remain explicit destructive
operations for their named data. They are not disk-maintenance shortcuts.

## Keep caches from growing again

- Agi-stack dev/test profiles use `debug = 1` and `incremental = false`.
  Workspace Core's Cargo wrapper applies equivalent defaults. This retains line
  information for backtraces while reducing debugger variable detail. Disabling
  incremental compilation trades some edit/rebuild speed for less disk usage.
- For a debugging session that needs full symbols or incremental builds, use
  `CARGO_PROFILE_DEV_DEBUG=2 CARGO_PROFILE_TEST_DEBUG=2 CARGO_INCREMENTAL=1`
  with the build command. These overrides are explicit and temporary. Changing
  profiles can cause a one-time dependency rebuild; it does not remove old files.
- Build Workspace Core through `scripts/avernet-bcs/cargo.sh` or the existing Make
  and Desktop scripts. Its canonical output is `.cache/avernet-bcs/target`.
  Direct Cargo invocation inside the vendored workspace creates another large
  `third_party/avernet-bcs/target`. Agi-stack and Workspace Core use different Rust
  toolchains, so their canonical targets stay separate.
- Before a large build or repository copy, check `df -h .` and `make disk-usage`.
  Reuse an existing checkout when isolation is unnecessary. Do not copy build
  targets, dependency trees or runtime data into validation snapshots.
- Once a task's branch is merged and validation is finished, inspect its status
  and remove that task's temporary worktree with `git worktree remove PATH`.
  Never use `--force` to discard unreviewed files or remove another task's checkout.
  Keep requested reports separately and remove task-owned temporary test copies.
