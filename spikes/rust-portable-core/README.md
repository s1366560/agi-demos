# `rust-portable-core` — Decision Spike

> **Purpose.** Falsify (or confirm) the headline claim from the rewrite plan:
> *a single Rust core can be written **once** and run both as a cloud server
> binary **and** as an embeddable package on device (browser-WASM / desktop /
> mobile), offline-capable, by swapping only the platform adapters.*
>
> This is a **throwaway spike**, not production code. It implements the thinnest
> meaningful vertical slice of the real domain: **Episode → Memory ingestion +
> semantic-ish search**, mirroring the existing Python `MemoryRepository` port.

## TL;DR — what was proven

| # | Claim under test | Verdict | Evidence |
|---|---|---|---|
| 1 | **Core async is runtime-agnostic** (no tokio baked into core) | ✅ PASS | `adapters-mem` test `ingest_and_search_runs_without_tokio` runs the full pipeline under `futures::executor::block_on`; core has zero `tokio` / `std::time` deps |
| 2 | Same core compiles to a **native server** | ✅ PASS | `apps/server` (axum+tokio) serves `/health`, `POST /episodes`, `GET /memories/search`; verified via curl |
| 3 | Same core compiles to **browser WASM** *unchanged* | ✅ PASS | `cargo build --target wasm32-unknown-unknown` of core + adapters-mem + bindings-wasm, **zero core code changes** |
| 4 | WASM build is **usable from JS** and **small** | ✅ PASS | `wasm-pack` nodejs build + `harness/node-smoke.cjs` round-trips ingest→search. Size **95 KB raw / ~49 KB gzip** |
| 5 | A **real embedded DB** can back the same port on device | ✅ PASS | `adapters-sqlite` (rusqlite, **bundled C SQLite**) implements `MemoryRepository`, overrides `search_by_project` to push the filter into SQL; test green |
| 6 | Adapters are genuinely **swapped per platform** (not one-size-fits-all) | ✅ PASS (by construction) | bundled-SQLite **cannot** target `wasm32-unknown-unknown` (`stdio.h` not found) → browser must use a different storage adapter behind the *same* port. This is the hexagonal boundary working as intended. |

**Still open** (next slices, not yet done): UniFFI iOS/Android bindings, Tauri
desktop shell, `sqlite-vec` real vector search, performance/size scorecard vs
the Python baseline. See *Open items* below.

## Why this is the crux

The entire portability thesis hinges on one thing: **the core must not assume a
runtime**. Python's `async` is tied to an event loop; the naive Rust port would
reach for `tokio` and instantly become un-embeddable in the browser. So the core
here:

- uses `async-trait` + `futures` only — **no** `tokio`, **no** `tokio::spawn`;
- injects time via a `Clock` port — **no** `std::time` (which panics/needs JS on wasm);
- expresses every side-effect as a **port** (`MemoryRepository`, `LlmPort`,
  `EmbeddingPort`, `Clock`), so each platform supplies its own adapter.

That is exactly the existing Python hexagonal boundary (`domain/ports/`), re-expressed as Rust traits.

## Layout

```
spikes/rust-portable-core/
├── Cargo.toml                  # workspace (resolver=2, size-optimized release profile)
├── crates/
│   ├── core/                   # PORTABLE: model + ports + MemoryService. No tokio. No std::time.
│   │   └── src/{model,ports,service,util,lib}.rs
│   ├── adapters-mem/           # In-memory + stub adapters (+ the runtime-agnostic test)
│   ├── adapters-sqlite/        # On-DEVICE storage: embedded SQLite via rusqlite (bundled C)
│   └── bindings-wasm/          # BROWSER/JS binding via wasm-bindgen (future_to_promise)
├── apps/
│   └── server/                 # SERVER target: axum + tokio (runtime lives ONLY here)
└── harness/
    └── node-smoke.cjs          # Node smoke test for the wasm-pack build
```

The dependency direction is strict: `core` depends on nothing platform-specific;
every other crate depends on `core`. `tokio` exists in exactly one place (`apps/server`).

## Build / run / test per target

All cross-target commands use the **rustup** toolchain (Homebrew's `rust` only
has the host target). Prefix with the rustup cargo:

```bash
cd spikes/rust-portable-core
export PATH="$HOME/.cargo/bin:$PATH"   # use rustup's cargo (has wasm32 target)
```

### 1. Native workspace (build + all tests)

```bash
cargo build --workspace
cargo test  --workspace
```

### 2. Server target (manual e2e)

```bash
cargo run -p memstack-server        # listens on http://127.0.0.1:8088
# in another shell:
curl -s localhost:8088/health
curl -s -X POST localhost:8088/episodes \
  -H 'content-type: application/json' \
  -d '{"project_id":"p1","author_id":"u1","content":"local-first memory engines"}'
curl -s 'localhost:8088/memories/search?project_id=p1&q=memory'
```

### 3. Browser-WASM target

```bash
# plain cross-compile (proves the core is wasm-clean):
cargo build --target wasm32-unknown-unknown \
  -p memstack-core -p memstack-adapters-mem -p memstack-bindings-wasm

# full JS package + node smoke test:
wasm-pack build crates/bindings-wasm --release --target nodejs
node harness/node-smoke.cjs
```

> **wasm-opt gotcha:** recent rustc/LLVM emit bulk-memory ops that the bundled
> `wasm-opt` rejects. Fixed in `crates/bindings-wasm/Cargo.toml` via
> `[package.metadata.wasm-pack.profile.release] wasm-opt = ['-Oz',
> '--enable-bulk-memory', '--enable-nontrapping-float-to-int']`.

### 4. On-device SQLite adapter

```bash
cargo test -p memstack-adapters-sqlite   # compiles bundled SQLite from C (~30-60s first time)
```

## The platform-adapter boundary (important finding)

`adapters-sqlite` uses `rusqlite { features = ["bundled"] }`, which compiles the
SQLite C amalgamation. That is perfect for **native device** targets (iOS,
Android, desktop) but **cannot** build for `wasm32-unknown-unknown`:

```
sqlite3.c: fatal error: 'stdio.h' file not found   # no libc on bare wasm
```

This is not a failure — it is the thesis working. The **same** `MemoryRepository`
port is satisfied by **different** adapters per platform:

| Platform | Storage adapter | Status in spike |
|---|---|---|
| Server | (prod) Postgres + pgvector | stubbed by `adapters-mem` |
| Desktop / iOS / Android | `adapters-sqlite` (embedded SQLite) | ✅ implemented |
| Browser | `adapters-mem` today; (prod) IndexedDB / wa-sqlite | ✅ in-mem path |

## Toolchain notes

- `rustc`/`cargo` **1.96** via both Homebrew (host-only) and rustup (added
  `wasm32-unknown-unknown`). Use `~/.cargo/bin` for anything cross-target.
- `wasm-pack` 0.15, `wasm-bindgen` 0.2.
- `rusqlite` 0.32 (`bundled`) needs a C compiler (Xcode CLT present).

## Open items (next spike slices)

1. **UniFFI mobile** — generate Swift/Kotlin bindings from `core`; build an iOS
   static lib (xcrun present) and an Android `.so` (needs **Android NDK** — not
   yet installed; flag before doing).
2. **Tauri desktop** — wrap `core` in a Tauri app to prove the PC shell.
3. **`sqlite-vec`** — replace the toy hash-embedding search with a real on-device
   vector index.
4. **Scorecard** — measure binary/wasm size, cold-start, and ingest/search
   latency vs the current Python service; fill the go/no-go thresholds in
   `~/.copilot/session-state/.../files/rust-spike-plan.md`.

## Verdict so far

The make-or-break risk (**runtime-agnostic core → one codebase, server + browser
+ device**) is **confirmed** with working, tested artifacts across three distinct
compile targets and a real embedded database. Nothing observed contradicts the
plan's recommendation of **Rust as the portable-core language**. Remaining work
is breadth (more targets) and quantified metrics, not a fundamental unknown.
