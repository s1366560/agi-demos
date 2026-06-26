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
| 7 | Core packages as a **native mobile library** (Swift/Kotlin) | ✅ PASS (codegen + iOS arch) / ⛓️ blocked on SDK | `bindings-uffi` (UniFFI) compiles against the real core; **Swift + Kotlin** bindings generated (`generated/`); core + in-mem adapter cross-compile to `aarch64-apple-ios`. Final device `.a`/`.so` needs full **Xcode iOS SDK** / **Android NDK** (not installed here) |
| 8 | The **plugin host itself is a portable port** (untrusted tools sandboxed in WASM, host runs on every target *incl. browser*) | ✅ PASS | `adapters-wasmi` implements a new `ToolHost` port over the pure-Rust **wasmi** interpreter, runs a sandboxed `.wat` tool (test green), and **also compiles to `wasm32-unknown-unknown`** — i.e. the same host runs natively *and* wasm-in-wasm inside the browser core. Wasmtime would swap in for server/desktop speed behind the same port. |
| 9 | **Cross-layer hot-plug**: runtime WASM-tool hot-swap + extension manifest enable/disable, with **in-flight rounds pinned to the old version** (round-boundary atomic apply) | ✅ PASS | `crates/plugin-host` (`ArcSwap<ToolRegistry>` registry + `PluginHost` enable/disable + `PluginShape` classification) and runtime `WasmTool::from_bytes` in `adapters-wasmi`; **9 tests green** (`tests/registry.rs` 5, `tests/lifecycle.rs` 3, `tests/hot_swap.rs` 1). `cargo run -p hotplug-demo` shows v1→v2 hot-swap (new call gets v2, a handle holding the old snapshot still gets v1), enable/disable lifecycle, and shape classification. Mirrors OpenClaw's registry lifecycle but **stronger**: the swap binds to the ReAct round boundary. |

**Still open** (next slices, not yet done): final iOS `.a` / Android `.so` device
artifacts (need Xcode iOS SDK + NDK installs), Tauri desktop shell, `sqlite-vec`
real vector search, performance/size scorecard vs the Python baseline. See
*Open items* below.

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
│   ├── adapters-wasmi/          # PLUGIN HOST: ToolHost port over pure-Rust wasmi (sandboxes untrusted tools; compiles to wasm32 too) + runtime-loadable WasmTool (hot-swap)
│   ├── bindings-wasm/          # BROWSER/JS binding via wasm-bindgen (future_to_promise)
│   └── bindings-uffi/          # MOBILE binding via UniFFI -> generates Swift (iOS) + Kotlin (Android)
├── crates/plugin-host/          # HOT-PLUG: ArcSwap<ToolRegistry> + PluginHost enable/disable + PluginManifest/PluginShape (OpenClaw-style capability registry)
├── apps/
│   ├── server/                  # SERVER target: axum + tokio (runtime lives ONLY here)
│   └── hotplug-demo/            # DEMO: native register -> manifest enable+shape -> WASM v1->v2 hot-swap+in-flight isolation -> enable/disable
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

### 5. Mobile native package (UniFFI → Swift / Kotlin)

```bash
# build the host lib once (used for library-mode binding generation):
cargo build -p memstack-bindings-uffi

# generate idiomatic native bindings from the SAME core:
cargo run -p memstack-bindings-uffi --bin uniffi-bindgen -- \
  generate --library target/debug/libmemstack_mobile.dylib --language swift  --out-dir generated/swift
cargo run -p memstack-bindings-uffi --bin uniffi-bindgen -- \
  generate --library target/debug/libmemstack_mobile.dylib --language kotlin --out-dir generated/kotlin

# cross-compile the core for the iOS architecture (pure-Rust path, no Apple SDK needed):
cargo build -p memstack-core -p memstack-adapters-mem --target aarch64-apple-ios --release

# full device static lib (needs full Xcode iOS SDK installed — see note):
cargo build -p memstack-bindings-uffi --target aarch64-apple-ios --release   # -> libmemstack_mobile.a
```

The generated Swift API the iOS app calls (auto-derived from the Rust core, see
`generated/swift/`):

```swift
public convenience init(dbPath: String)                                        // open on-device store
func ingest(projectId: String, authorId: String, content: String) -> String   // -> Memory JSON
func search(projectId: String, query: String, limit: UInt32) -> String         // -> [Memory] JSON
```

> **Device-artifact prerequisites (environment, not architecture):**
> - **iOS `.a`** needs the `iphoneos` SDK, which ships only with **full Xcode**
>   (this machine has Command Line Tools only → `xcrun --sdk iphoneos` fails when
>   `cc` compiles bundled SQLite). The pure-Rust core *does* cross-compile to
>   `aarch64-apple-ios` here; only the C-SQLite step is gated on the SDK.
> - **Android `.so`** needs the **Android NDK** (not installed). Kotlin bindings
>   still generate without it (codegen is host-side).
>
> `generated/` is checked in as **evidence** of the native surface; normally it
> is a build artifact.

### 6. Plugin host — sandboxed third-party tools (extensibility axis)

MemStack is itself a plugin platform (L1 Tool / L2 Skill / L3 SubAgent / MCP are
all extension points). The spike's second axis proves that **untrusted** tools
can be hosted **behind a port**, on every target:

```bash
# native: invoke a sandboxed .wat tool through the ToolHost port
cargo test -p memstack-adapters-wasmi

# the host ITSELF compiles to wasm -> same untrusted tool runs inside the
# browser core (wasm-in-wasm), no server round-trip required:
cargo build -p memstack-adapters-wasmi --target wasm32-unknown-unknown
```

`adapters-wasmi` adds a `ToolHost` port to the core and implements it with the
pure-Rust **wasmi** interpreter. Trust × platform decisions both fold into this
one port:

- **Trust axis** — trusted built-in tools are plain `dyn Trait` compiled into the
  core (native speed); untrusted third-party / MCP tools run *only* inside the
  wasm sandbox. (Iron rule: never load untrusted code via `cdylib`/in-process
  dynamic libs.)
- **Platform axis** — the host runtime is swapped behind the port: **Wasmtime**
  on server/desktop (JIT + fuel/epoch quotas), **wasmi/wasmer** on iOS (no JIT),
  **wasmi** in the browser (wasm-in-wasm) or a Web-Worker / server proxy. `wasmi`
  is the *universal-portable* fallback because it compiles to every target the
  core does — proven above.

> **core-as-guest vs core-as-host.** Claims 3–4 proved *core-as-guest* (the whole
> core compiled to wasm). This slice adds *core-as-host* (the core embeds a
> runtime to load tool plugins). They only tension in the browser, where the core
> is already wasm; `wasmi` resolves it by interpreting wasm *inside* wasm.

### 7. Cross-layer hot-plug demo (hot-swap + extension lifecycle)

Building on the plugin host, this slice proves the core can **hot-swap tools and
enable/disable extensions at runtime** without restarting — and that the swap is
safe for in-flight work. It mirrors OpenClaw's plugin-registry lifecycle
(`openclaw/openclaw:src/plugins/runtime.ts`) but binds the swap to the ReAct
round boundary, which is strictly stronger.

```bash
# the hot-plug registry + lifecycle + wasm hot-swap tests (9 total, all green):
cargo test -p memstack-plugin-host          # registry.rs (5) + lifecycle.rs (3)
cargo test -p memstack-adapters-wasmi        # incl. hot_swap.rs (v1 n*3+7 -> v2 n*10)

# runnable narrative:
cargo run -p hotplug-demo
```

`crates/plugin-host` adds an OpenClaw-style capability registry over the core:

- **`HotPlugRegistry`** — `Arc<ArcSwap<ToolRegistry>>` holding a name-sorted
  `Vec<Arc<dyn Tool>>`. `register/replace/unregister` rebuild a new immutable
  `Arc<ToolRegistry>` via `rcu` and atomically swap the pointer; reads are
  lock-free. `snapshot()` = `load_full()` — **holding a snapshot pins the old
  version**, so a round that started before a swap keeps calling the old tool.
- **`PluginHost`** — `enable(manifest)` instantiates the manifest's declared
  tools through a `ToolFactory` and registers them, tracking `plugin_id ->
  [tool_names]`; `disable(plugin_id)` unregisters that set. Pure set arithmetic +
  pointer swap (deterministic; the *semantic* "is this tool applicable" stays an
  agent decision per the Agent-First rule).
- **`PluginManifest` / `PluginShape`** — JSON manifest mirroring OpenClaw's
  `openclaw` package field (tools/skills/providers); `shape()` classifies by
  actual capability kinds: `PlainCapability` / `HybridCapability` / `HookOnly` /
  `NonCapability`.

`adapters-wasmi` gains **`WasmTool`** — a `plugin_host::Tool` loaded from wasm
**bytes at runtime** (`from_bytes` / `from_wat`, export `run(i32)->i32`),
replacing the construction-time baked tool. The demo loads v1 (`n*3+7`), swaps in
v2 (`n*10`) live, and asserts a pre-swap snapshot still resolves v1.

> **Design write-up:** the synthesis behind this slice (capability registration,
> plugin shapes, pluggable harness, hot-plug lifecycle state machine) lives in
> `agi-stack/docs/architecture/07-plugin-runtime-architecture.md`, with the
> source-level OpenClaw evidence in
> `agi-stack/docs/research/openclaw-runtime-internals.md`.

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
  `wasm32-unknown-unknown`, `aarch64-apple-ios`, `aarch64-apple-ios-sim`). Use
  `~/.cargo/bin` for anything cross-target.
- `wasm-pack` 0.15, `wasm-bindgen` 0.2.
- `uniffi` 0.28 (proc-macro mode via `setup_scaffolding!`, library-mode bindgen).
- `rusqlite` 0.32 (`bundled`) needs a C compiler (Xcode CLT present); the iOS
  device build additionally needs the **full Xcode iOS SDK**.

## Open items (next spike slices)

1. **Mobile device artifacts** — codegen + iOS-arch compile are DONE. Remaining:
   build the final iOS `.a` (install **full Xcode** for the `iphoneos` SDK) and
   the Android `.so` (install **Android NDK**), then run on a simulator/emulator.
2. **Tauri desktop** — wrap `core` in a Tauri app to prove the PC shell.
3. **`sqlite-vec`** — replace the toy hash-embedding search with a real on-device
   vector index.
4. **Wasmtime host + WIT contracts** — add a Wasmtime-backed `ToolHost` adapter
   for server/desktop speed (fuel/epoch quotas) and define the tool ABI as a
   WIT / Component-Model interface instead of the raw numeric `.wat` used here.
5. **Scorecard** — measure binary/wasm size, cold-start, and ingest/search
   latency vs the current Python service; fill the go/no-go thresholds in
   `~/.copilot/session-state/.../files/rust-spike-plan.md`.

## Verdict so far

The make-or-break risk (**runtime-agnostic core → one codebase, server + browser
+ device**) is **confirmed** with working, tested artifacts across server,
browser-WASM, an embedded database, and a native **mobile** binding (Swift +
Kotlin generated from the same core; iOS-arch cross-compile verified). The
**extensibility axis** is also confirmed: untrusted tools run sandboxed behind a
`ToolHost` port whose wasm host compiles to every target (incl. the browser
core). The **hot-plug axis** is confirmed too: a `ToolRegistry` behind `ArcSwap`
hot-swaps tools and enables/disables extensions at runtime, with in-flight rounds
pinned to the old version at the round boundary — a deterministic strengthening of
OpenClaw's restart-based model. Nothing observed contradicts the plan's
recommendation of **Rust as the portable-core language**. Remaining work is
breadth (final device artifacts behind SDK/NDK installs, Tauri desktop, a
Wasmtime host adapter + WIT contracts) and quantified metrics — not a fundamental
unknown.
