---
name: agi-demos-desktop-parity-delivery
description: Deliver and verify MemStack native desktop changes in agi-demos against the design-prototype or Web product surface while preserving the Electron shell, Rust sidecar, IPC, encrypted-vault, signing, and updater boundaries. Use for implementation, parity repair, or QA work scoped to agi-stack/apps/desktop; do not use for generic Web QA, mobile work, or unrelated desktop applications.
---

# Deliver MemStack Desktop Parity

Treat this as a narrow implementation-and-evidence playbook for
`agi-stack/apps/desktop`.

## Establish the contract

Read and obey the repository-root `AGENTS.md` before acting. Keep its TDD, security, GitNexus,
Agent First, and dirty-worktree requirements active throughout the delivery.

Collect or discover these inputs before editing:

- the requested desktop surface, user flow, and observable acceptance result;
- the exact `design-prototype/memstack-desktop-agent-mission-control` artifact or Web surface used
  as reference, pinned both to the overall reference revision and to the last revision that changed
  the requested surface;
- whether adjacent reference changes after that surface revision belong to this delivery or are
  explicitly out of scope;
- matching locale, viewport, user state, data state, and interaction state;
- the renderer, Electron main/preload, Rust sidecar, persistence, packaging, or update boundaries
  that may be affected;
- whether delivery stops at local QA or includes bundle/release validation.

Use the prototype as visual and interaction evidence, and use Web as product behavior or contract
evidence. Treat the current desktop implementation, `agi-stack/apps/desktop/ELECTRON.md`, and
repository rules as authoritative for native security and runtime behavior. Do not copy a prototype
mock or Web implementation when it would weaken a native boundary.

Inspect `git status --short` first. Preserve every unrelated tracked or untracked user change.
Restrict diffs, formatting, and validation artifacts to the requested surface; never clean or reset
the shared dirty tree. When the task overlaps an already dirty path, capture a task-start snapshot
in a repository-external, mode-`0700` temporary evidence directory: status, separate
`git diff --binary` and `git diff --cached --binary` patches, plus protected copies and hashes of
relevant overlapping untracked files. Compare that snapshot with the final state to derive the
task-only delta; do not attribute the entire final worktree diff to this task. Remove only this
task-created temporary directory after its findings have been included in the handoff.

## Map the change before editing

1. Run GitNexus `query` for the desktop flow and its reference contract.
2. Check whether the index describes the current Electron implementation. If it is stale, refresh it
   with the repository-supported GitNexus analyze command before relying on results.
3. Run GitNexus `impact` upstream for every symbol that may change, including functions, classes,
   methods, React components, hooks, exported constants, types, and enums.
4. Report direct callers, affected execution flows, and risk. Warn before editing any HIGH or
   CRITICAL target.
5. Read the referenced prototype/Web source and the current desktop implementation. Build a compact
   parity matrix covering visuals, interactions, data/contract behavior, and native-only behavior.
6. Define the expected tests and evidence before implementation.

Do not use text search as a substitute for GitNexus impact analysis. Use `rg` only to supplement
graph results or locate static assets and copy.

When severity, acceptance equivalence, or an intentional deviation requires semantic judgment, use
an available agent/subagent structured tool-call. Persist one JSONL record per judgment in the
task's protected temporary evidence directory with `agent_id`, `tool_name`, `input`, `output`,
`rationale`, and `latency_ms`. Measure elapsed wall time around the call when the tool does not
return latency. Redact secrets, tokens, personal data, and full source/diff bodies before writing;
store compact references and summaries instead. Never include the evidence directory in the
worktree or commit scope. If no structured judgment mechanism is available, report the observation
without assigning a P0/P1/P2 verdict and do not use an unlogged subjective label to authorize an
edit.

## Implement with TDD

Add or adjust the smallest focused failing test before changing behavior. Prefer existing test
harnesses and fixtures:

```bash
pnpm --dir agi-stack/apps/desktop test
cargo test --manifest-path agi-stack/Cargo.toml -p agistack-desktop-sidecar
```

Run the narrow affected tests during iteration only when the existing runner documents a supported
file or test-name filter; otherwise run the complete nearest relevant test command. Then run the
complete relevant command before handoff.
Use structured runtime metadata and contracts; do not add keyword, regex, or message-text
heuristics for semantic decisions. Keep renderer-only presentation logic separate from Electron
process and Rust runtime authority.

Preserve these boundaries whenever the change crosses them:

- Keep the renderer sandboxed with context isolation, no Node integration, and an allow-listed
  preload bridge. Never expose raw `ipcRenderer`.
- Let Electron own sidecar startup, shutdown, authenticated private-pipe handshake, command
  timeouts, and capped crash recovery. Never launch the sidecar directly for native validation.
- Keep trusted sessions and Provider API keys in the Rust application-managed encrypted vault.
  Never reintroduce Keychain, Credential Manager, Secret Service, plaintext persistence, or secret
  logging.
- Preserve package signing, nested sidecar verification, hardened runtime/notarization, and
  Authenticode rules when packaging changes.
- Preserve the separation between local bundles with publishing disabled and production tag
  bundles with validated updater metadata. Never claim update-feed validation from an unpackaged
  renderer run.

## Verify parity and native behavior

Use `browser:control-in-app-browser` for deterministic renderer QA routes, console inspection, and
same-viewport captures. Compare reference and implementation with identical viewport, locale, data,
and interaction state. A renderer QA route is supporting evidence, not proof of native behavior.
Start the renderer-only development surface, when needed for Browser QA, with:

```bash
pnpm --dir agi-stack/apps/desktop run dev
```

This command is permitted only as Browser supporting evidence. Do not call it a native-client
launch. Do not reuse a fixture whose locale, initial expansion state, or data differs from the
reference; configure an existing fixture to the required state or add a deterministic task-scoped
fixture.

Launch the native client only from the repository root:

```bash
make -C agi-stack run-desktop
```

Do not use `pnpm run dev`, raw `electron-vite dev`, or a directly launched sidecar as a native QA
substitute. Use `computer-use:computer-use` against the launched Electron application to verify the
requested end-to-end interaction and the native boundaries actually affected by the change.

Before native interaction, inspect the repository for an existing supported disposable profile,
test account, or application-data isolation mechanism. Use it when present. Do not invent an
undocumented environment variable or launch flag, inspect real credentials, or mutate a user's
vault to manufacture evidence. If no supported isolation mechanism exists, keep native QA
non-destructive, use only an already authorized test account, and report vault/session persistence
as unverified. If isolation or persistence proof is itself an affected boundary or acceptance row,
that missing proof blocks the overall completion claim.

Run validation proportional to the touched boundary:

- renderer behavior: focused tests when filtering is supported, full desktop test command,
  type/build checks, Browser QA, and a native interaction smoke for the changed flow;
- preload/main/sidecar behavior: focused TypeScript/Rust tests plus native Electron validation;
- packaging, signing, or updater behavior: build the bundle and run
  `make -C agi-stack desktop-bundle-smoke`; verify only the signing/update properties available in
  the current environment;
- visual parity: retain same-state full-view and focused captures and record intentional product
  deviations.

Inspect console/runtime errors and accessibility behavior. Do not declare parity from screenshots
alone when the task changes interaction, persistence, IPC, or runtime behavior.

## Close with traceable evidence

Run GitNexus `detect_changes` over the final worktree before every handoff; if a commit is requested,
run it again immediately before that commit. Reconcile its
affected symbols and flows with the pre-change impact report and the task-only delta derived from
the task-start snapshot. Treat `detect_changes` as shared-worktree evidence, not proof that every
reported change belongs to this delivery. Do not attribute pre-existing dirty-tree changes to it.

Return a compact evidence packet containing:

- reference artifacts and the matched state;
- changed files and the parity matrix result;
- GitNexus impact risk and final affected flows;
- tests, build, Browser QA, native launch, and Computer Use results;
- bundle/signing/updater checks when applicable;
- remaining intentional deviations, environment limits, or blockers.

Finish only when every stated acceptance row passes, relevant tests and builds pass, the native app
has been exercised for native-affecting work, GitNexus final scope matches the intended change, and
the structured judgment record has no unresolved actionable P0/P1/P2 parity findings. If structured
severity judgment is unavailable, finish only against the explicit acceptance rows and list every
remaining observation without a severity label. Do not commit or push unless the user requests it.

## Degrade without overstating

- If the native app cannot launch, complete focused tests, build/static checks, and Browser QA where
  possible, then report native verification as blocked. Never convert renderer evidence into a
  native pass.
- If production signing, notarization, Authenticode, or release credentials are unavailable, run
  local bundle checks and label production release verification untested. If production release
  verification is an affected boundary or explicit acceptance row, this blocks the overall
  completion claim.
- If the reference conflicts with current native security or runtime rules, preserve the native
  boundary, document the intentional deviation, and request product direction only when the
  acceptance result remains ambiguous.
- If GitNexus remains stale or unavailable after the supported refresh attempt, stop before editing
  symbols whose impact cannot be established; report the missing blast-radius evidence.
- If required live data or authentication state is unavailable, use an existing deterministic QA
  fixture for presentation checks and report integration behavior as unverified.

Track the terminal session and process ownership for every Vite or Electron process started by this
task. After QA, stop only those task-owned processes through the same terminal or documented scoped
stop path, unless the user explicitly asks to keep them running. Confirm their ports and child
sidecar processes are no longer owned by the task; do not use a broad or unverified raw kill.
