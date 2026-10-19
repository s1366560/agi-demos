# MemStack Computer Use replication plan

## Current implementation: 2026-10-14

This plan was written for the initial macOS vertical slice on 2026-10-13.
The historical sections below describe that implementation, not the current
protocol, tools, security policy, or acceptance results. Current implementation
and executable validation are documented in
[`computer-use-implementation.md`](computer-use-implementation.md); current
reference analysis is in
[`chatgpt-computer-use-analysis.md`](chatgpt-computer-use-analysis.md).

The current first-party v2 plugin supplies 26 scoped tools on macOS, Windows,
X11 and Wayland. It uses authenticated inherited pipes and
`MemstackComputerUseIPC-2`, owned observations, native application grants,
artifact-backed media, actual image content blocks, recording, connectors,
and a cloud device bridge. The initial shared socket, IPC-1 bootstrap, base64
icon data URLs, global stop/resume flag and hardcoded target-name classification
below have been replaced. The historical test counts are not current results.

The follow-up requested on 2026-10-14 adds native menu-bar status, per-session
pause/resume/stop, canonical target application icons, and the latest authorized
window preview in settings, session activity, consent and tool results. Native
icons use separate owned artifacts and are not sent to the visual model as
observations. Preview timestamps identify the last authorized screenshot;
status polling does not silently capture additional frames.

Pause releases input, recording and clipboard resources and invalidates prior
observations. Resumption checks current plugin, owner and run authority, requires
a new observation, and does not restart recording. Stopped sessions cannot be
revived. Background connector execution remains governed by its own grants.

Reference static assets and exported symbols establish the presence of native
status items, application icons and PIP window lookup. Native implementation
bodies and the reference menu's runtime pixels were not available in this
analysis. Original MemStack graphics are used; proprietary assets are not copied.
Interactive Windows/Wayland, physical hardware takeover, dedicated macOS Locked
Use, external account writes and live cloud model execution remain separate
unverified acceptance boundaries documented in the current implementation.

## Historical initial vertical slice: 2026-10-13

Companion to `chatgpt-computer-use-analysis.md` (the reverse-engineering
findings). This document maps the observed ChatGPT.app architecture onto
MemStack's desktop stack (Electron + Rust sidecar) and records the current
implementation status of the vertical slice.

## 1. Architecture mapping

| ChatGPT.app component | Role | MemStack counterpart | Status |
|---|---|---|---|
| `SkyComputerUseService` (Swift) | AX trees, screenshots, input synthesis | `agi-stack/apps/desktop/cua-helper` (Swift) | Implemented (core); gaps below |
| `@oai/sky` mac client (`client.js`, `native-pipe.js`) | typed IPC client, framing, handshake, bootstrap | `agi-stack/crates/adapters-cua` (`client.rs`, `framing.rs`) | Implemented + tested |
| Agent-facing `Sky` API + plugin SKILL.md | tool surface for the model | `adapters-cua` `host.rs`: `computer_*` ToolHost (10 tools with schemas) | Implemented + tested |
| `withComputerUsePolicy` (freeze args, 3-state target policy, HITL elicitation) | safety layer | sidecar `AuthorizedRunToolHost` + `HitlKind::Permission` grants; `tool_effects()` maps Read/Mutate; forbidden-target tier in `CuaToolHost` | Mostly wired (org-policy tier and per-app consent persistence future; §4) |
| Telemetry (approval requested/resolved, tool_called) | audit | sidecar invocation ledger + timeline items | Reuses existing machinery; no CUA-specific events yet |
| Separate Sparkle updater for the CUA service | lifecycle | helper binary shipped beside the sidecar; update via app updater | Deferred |
| Lock-screen guardian + login authorization plugin | continuity under lock | none | Deferred (privilege-sensitive) |
| Audio recording (AVFoundation) with high-risk approval | media capture | none | Deferred |
| Apple Events connectors (Messages/Calendar/Contacts) | specialized MCP-style tools | follow the existing MCP/plugin host pattern | Deferred |
| Skyshot timeline UX (screenshot cards) | rich tool-result rendering | `TimelineToolKind` + `DesktopToolResultRendererBridgeV2` slot | Deferred (frontend) |

## 2. Wire contract (implemented)

Identical shape to the reference transport (analysis section 2), renamed for
MemStack:

- Unix domain socket: default `<tmp>/memstack-cua/helper.sock`.
- 4-byte little-endian length framing, 8 MiB cap (`framing.rs`).
- JSON-RPC 2.0; `ping` handshake with `MemstackComputerUseIPC-1` version match;
  mismatch raises `incompatible_client_version`.
- Methods: `ping`, `accessibility_status`, `list_apps`, `get_app_state`
  (skyshot: AX text + window screenshot), `perform_action {app, action}`.
- Action kinds: `click`, `drag`, `type_text`, `press_key`, `scroll`,
  `set_value`, `secondary_action`, `paste`.
- Bootstrap: on connect failure the client spawns the helper binary
  (`MEMSTACK_CUA_HELPER_PATH` or beside the sidecar executable) and retries —
  the ensure-service pattern.

## 3. Tool surface (implemented)

`CuaToolHost` advertises:

| Tool | Effect | Notes |
|---|---|---|
| `computer_list_apps` | Read | running apps |
| `computer_get_app_state` | Read | diff-by-default AX text + screenshot |
| `computer_click` | Mutate | element_index or window-relative x/y, button, count, held chord |
| `computer_type_text` | Mutate | CGEvent unicode typing |
| `computer_press_key` | Mutate | xdotool-style chords (`super` = Command) |
| `computer_scroll` | Mutate | element or coordinate, direction, pages |
| `computer_set_value` | Mutate | AX value replacement (no keystrokes) |
| `computer_drag` | Mutate | window-relative from/to |
| `computer_secondary_action` | Mutate | named AX action, never guessed |
| `computer_paste` | Mutate | text/md/html, pasteboard restored |

Workflow contract carried over from the reference SKILL.md and encoded in tool
descriptions: element-first targeting, observe-after-act (indexes valid only
against the latest `computer_get_app_state`), coordinate fallback, diff output
by default, `stale_element` error to force refresh, ~1 s post-action settle.

## 4. Authority and HITL wiring

Already in place via the sidecar's existing machinery:

- `computer_use_tool_host()` joins the tool surface on macOS when the helper
  binary is discoverable (`local_runtime/mod.rs`, next to the browser host).
  `make -C agi-stack run-desktop` builds and stages the helper
  (`desktop-cua-helper` target; skipped off-macOS or without swiftc).
- `tool_effects()` maps onto `tool_authority::ToolMetadata` and flows into
  `AuthorizedRunToolHost::with_dynamic_metadata`; every Mutate tool therefore
  consumes a permission grant (`requires_grant()`), riding the existing
  `HitlKind::Permission` request/respond path and permission profiles
  (ReadOnly blocks the whole family).
- Forbidden-target safety tier implemented in `CuaToolHost::call`
  (`cua_target_forbidden` hard denial before any prompt): Keychain Access,
  Passwords, System Settings/System Preferences, matched by exact lowercase
  bundle id or display name. `MEMSTACK_CUA_ALLOW_FORBIDDEN_TARGETS=1` is the
  operator escape hatch (reference: `ComputerUseAllowForbiddenTargets`).
- The reference's org-policy tier (`denied` by the organization) and per-app
  consent persistence (session/always scopes with settings UI, like
  `BrowserRunToolHost` origin grants) remain future work — both need product
  decisions about the denylist source and the settings surface.

## 5. Verification status

- Swift helper: compiles clean (`swiftc -swift-version 5 -O`); smoke-tested
  live: version handshake (accept + reject), `accessibility_status`
  (correctly reports untrusted without TCC grant), `list_apps` against real
  running apps, `perform_action` error contract
  (`accessibility_permission_required`).
- **Real desktop run (2026-10-13, TCC granted)**: the helper executed inside
  the actual desktop app — a plan-mode run called `computer_list_apps` and
  `computer_get_app_state` against Finder successfully (`is_error: false` in
  the persisted timeline), and the `computer_use` presentation kind rendered
  with its icon. Dev-run TCC setup: `cua-helper --request-access`, or add
  `target/debug/cua-helper` manually under Privacy & Security > Accessibility
  and Screen Recording; ad-hoc rebuilds drop grants unless signed with
  `MEMSTACK_CUA_CODESIGN_IDENTITY`.
- First real-run defect found and fixed: the sidecar's static tool rosters
  (`authorized_tool_host.rs`) did not include the `computer_*` family, so the
  timeline redactor wiped their inputs/outputs to `[UNAVAILABLE]` — no row
  titles and no screenshot delivery. The rosters now carry the family
  (observation = Read, synthesis = Mutate) with regression tests;
  `computer_use_display` also falls back to a humanized tool title when the
  redacted input is unparseable.
- `agistack-adapters-cua`: 8 tests passing — framing round-trip,
  oversized-frame rejection, mock-server handshake + action round-trip,
  version-mismatch error kind, ToolHost routing/identity/effects, forbidden
  targets, and a binary end-to-end test that spawns the REAL helper and
  exercises bootstrap + handshake + `list_apps` + the TCC error contract.
  Clippy clean.
- Sidecar: full suite 992 passed / 2 failed — the 2 failures are
  pre-existing in the plugin operation-authority tests (plan catalog missing
  `skill_list`/`skill_loader`; `SkillDiscoveryToolHost::new` bails, likely in
  the in-flight `PluginNativeIdentityV2` / run-control work) and are
  unrelated to computer use (verified by control experiment with the roster
  change reverted).
- Frontend: `pnpm run build:electron` (tsc strict + electron-vite) passes;
  full frontend suite 4959 pass / 0 fail. `chatTimelinePresentation.tsx` is
  intentionally not node-unit-tested (React-context module; compile + browser
  QA per the established convention).

## 6. Timeline presentation (implemented)

- Rust: `TimelineToolKind::ComputerUse` (`display.kind = "computer_use"`),
  row title = target app, result summary = serialized element count, plus
  compact `computerUse` metadata `{app, screenshotUrl, icon}` on observe
  items (base64 image stays in `toolOutput`, same convention as
  `browser_screenshot`).
- TS: `ToolCallPresentationKind` union + whitelist, renderer-bridge
  `TOOL_RESULT_KINDS_V2`, `DesktopIcon` glyph, i18n
  (`session.toolKind.computer_use`, `chat.computerScreenshot`, en/zh), and a
  screenshot card rendering the skyshot image.

## 6b. Session UI parity (implemented 2026-10-13)

Replicating the reference's session affordances (evidence: strings
`CUAServiceStatusItemView`, `stopMenuItemClicked:`, `appshotAppIconFadeIn`,
`appIconLayer`, and the "explicitly stopped by the user for this turn"
model-guidance text):

- Menu bar status item (`cua-helper` `StatusItem.swift`): screen-plus-cursor
  template glyph drawn in code; appears on first observation/action, menu
  shows the target app plus Stop/Resume and Quit, auto-hides after 5 minutes
  idle (reference: `didAutoStop`). While stopped, every mutating call fails
  with the `user_stopped_session` contract error carrying model guidance to
  stop and yield (mirrors the reference's stopped-session error text).
- Target app icon: `list_apps` and `get_app_state` return a 32 px PNG data
  URL of the running app's icon (`NSRunningApplication.icon`).
- Appshot preview: the skyshot screenshot card renders the window image with
  the app icon overlaid at the top-left (fade-in, reference appshot style)
  and the icon in the card header.
- Concurrency note: the helper's socket server runs on a dedicated blocking
  accept/service thread, NOT dispatch sources — `NSApplication.run()` (which
  the status item requires) does not service dispatch-source handlers in
  this configuration; with `dispatchMain()` the socket worked but the status
  item did not. Main-thread UI mutation hops via `DispatchQueue.main`.

## 7. Roadmap after the vertical slice

1. End-to-end desktop validation (TCC grant path, screenshot permission).
2. Per-app consent persistence (session/always scopes + settings UI,
   mirroring `BrowserRunToolHost` origin grants) and an org-policy denylist
   source (bootstrap profile).
3. Agent skill doc shipped with the app (`skills/computer-use/SKILL.md`
   equivalent) so the model prefers purpose-built connectors over CUA.
4. ScreenCaptureKit-based capture (currently `screencapture` + `sips`).
5. Deferred parity items: window-list/window targeting (window2 semantics),
   drag handles, clipboard snapshot handles, lock-screen continuity, audio
   capture, Apple Events connectors as MCP tools.
