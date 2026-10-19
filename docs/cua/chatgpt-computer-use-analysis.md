# ChatGPT.app Computer Use analysis

## Current package check: 2026-10-14

`npx rea-agents setup` was run and scoped to Codex with a dry-run followed by
`--client codex --yes --json`. REA reports `ready` and aligned registration/skill;
there were no planned or applied configuration changes. No native decompiler was
configured or installed as part of setup.

The inspected installation is ChatGPT.app 26.1007.71326, bundle identifier
`com.openai.codex`, with `@oai/sky` 0.7.7. Its separately packaged native Computer
Use service is 26.1005.1001425, bundle identifier `com.openai.sky.CUAService`, an
arm64 Mach-O with minimum macOS 14.4. REA opened both the host executable and the
specific Computer Use component; the findings below concern the latter.

Current REA observations:

- `ev_b60aec64ecaa8b3e36d402709e12a5a46f7e7c2e1ee998ba4be3835a78505eb9`:
  native service package inspection; its nested inventory is
  `ev_8ccadbdbfe4fa62f3c15fb60e54fd31dc1a3ab3a47d7980e56bb9c9edcb19db9`.
- `ev_aa4db5660fff284f3ad08be51e15446e153a12c1730f371acd2d16f85cffac39`:
  complete Mach-O metadata. The response exceeded the MCP frame budget, so the
  retained record was exported rather than reanalysed or treated as truncated.
- `ev_31c0fdc777bf2b703faee03275c9b142fccd2477096093cedf341db6144a80a7` and
  `ev_ca28cb4a3f40ffec0e23a17e7a18d0e7618e425f8253ec060a81fb391b6962a6`:
  asset metadata includes `menubar-cursor`, `AppshotLogo`, `Screenshot`,
  `SoftwareCursor`, and separate running/paused Chronicle assets. Asset names
  establish packaged resources, not their actual runtime placement or behavior.
- `ev_d6a8d2ad2fc5553bec3d53bba441cd69e6d189611646fc9e516c7e4077792f38`:
  demangled shipped exports include
  `ComputerUsePIPWindowLookup.appIcon(pid:) -> NSImage`, window lookup by
  PID/window ID, modal/parent ownership resolution, and the internal
  `SkysightService.updateObservationPolicy` application method.
- `ev_49bc75d47413c72fd45730106ded6c3377f0651baa70105ec8494e64f7898056`:
  inert JavaScript analysis of all 41 macOS target files; no parse failures.
  Semantic relationships remain partial, with 1,521 unresolved graph facts.
  `ev_2e4ab2b6864e992b6e18aaf78b8afe7feb057420d2a926adfa2b6e403c01083b`
  selects the actual native-pipe module without repeating analysis.
- `ev_2f5c643c376cb5360803eac6804d79509e36d54b8a51701a69d33b19107211e3`:
  native service Info.plist confirms its accessory-app identity, icon declaration,
  system permission descriptions, and separately signed update configuration.

Ordinary static string inspection additionally finds
`CUAServiceStatusItemView`, `appIconLayer`, `appshotAppIconFadeIn`, and
`stopMenuItemClicked:`. These are useful UI reconstruction clues. They do not
prove animation timing, exact pixels, or menu actions. Reading the service's own
UI through its Computer Use client timed out; no reference menu action, recording,
personal-data connector, or unlock was executed. Exact dynamic reference UI
behavior remains unverified.

The shipped public client contracts expose window selection/observation, input,
text selection, holds, phased drag, clipboard handles, and separate audio capture.
The JavaScript policy wrapper freezes the approved app target and carries
structured approval/turn metadata. The internal Skysight export is not a public
Computer Use API declaration and does not establish a supported monitoring
workflow. Full native bodies and remote host behavior cannot be reconstructed
from these static observations alone.

MemStack implements the public capability set in its existing scoped tools and
private IPC-2 chain. This follow-up restores native menu state, owned program
icons, and the same authorized window preview in native and Electron surfaces.
It uses original MemStack graphics rather than redistributing OpenAI icon assets.
The reference's shared socket, implicit launch/background-input behavior, and
separate service updater do not replace this project's explicit target consent,
focus verification, private supervised pipes, or signed desktop update chain.
Current implementation and executable/native validation are documented in
`computer-use-implementation.md`; the historical sections below are not the
current MemStack implementation status.

## Historical static investigation: 2026-10-13

Date: 2026-10-13
Target: `/Applications/ChatGPT.app` (Codex desktop shell, Chromium 155.0.8059.40 framework, arm64)
Method: REA `npx rea-agents@6.4.0` artifact inspection plus macOS static tooling
(codesign entitlements, `otool -L`, Mach-O string tables, bundle inventory). No
native decompiler was available (Ghidra/IDA/Hopper unconfigured), so findings
come from shipped artifacts: entitlements, linked frameworks, bundled readable
JavaScript (`@oai/sky` npm package), bundled agent-facing documentation, and
Swift symbol/string tables. Every claim below cites its artifact. Nothing here
observes execution; all statements are static analysis.

Evidence anchors (REA):

- `ev_cdc0982d0431df6af646c81a54d4ce4194f7be270e352c16d307fae80b34a3ee` —
  `inspect_artifact` root, ChatGPT.app sha256
  `11987fdc3b01ea720a9351d433fcf738587e26ec3beb8ccb513c21cc99a9bb73`
- `ev_70fee48e02cb55a5faa2a9e960b27927c5bb0feb24ba9dcc76f318a81292ee00` —
  inventory graph: 24064 nodes / 26533 occurrences / 26507 edges

---

## 1. Component inventory

Computer Use is not one feature; it is a separately-versioned, separately-updated
subsystem inside the app bundle.

| Component | Path | Identity |
|---|---|---|
| CUA Node runtime | `Contents/Resources/cua_node/` | Node v24.21.0-cua.1 (custom build), `node_repl` entry, pinned via `manifest.json` |
| Orchestration library | `cua_node/lib/node_modules/@oai/sky/` | npm package `@oai/sky` v0.7.6, ES module, compiled TS under `dist/project/cua/sky_js/` |
| CUA native service | `cua_node/lib/node_modules/@oai/sky/Codex Computer Use.app` | bundle id `com.openai.sky.CUAService`, exe `SkyComputerUseService` (24.5 MB Swift Mach-O), v26.1005.1001425, `LSUIElement` |
| CLI client | `.../SharedSupport/SkyComputerUseClient.app` | bundle id `com.openai.sky.CUAService.cli` |
| Lock-screen guardian | `.../SharedSupport/CUALockScreenGuardian.app` | watches lock state; UDS `/tmp/com.openai.sky.CUAService/LockScreenLoginAuthorization.sock` |
| Privilege installer | `.../SharedSupport/Codex Computer Use Installer.app` | carries `CodexComputerUseAuthorizationPlugin.bundle` + `...InstallerTool` |
| Agent skill docs | `@oai/sky/docs/skills/oai_sky_lib/{macos,windows,linux}/SKILL.md`, `docs/sky-{window,window2,full-desktop}-api.md` | shipped agent-facing API references |
| Tool-surface plugin | `Contents/Resources/plugins/openai-bundled/plugins/computer-use/` | `.codex-plugin/plugin.json` v1.0.1001425 (version-locked to the service build) + `skills/computer-use/SKILL.md` |
| Messaging connector | `plugins/openai-bundled/plugins/messages/.mcp.json` | MCP server launched via `computer-use-client-launcher messages mcp` with `CODEX_HOME` passthrough |

Key packaging facts:

- The main app entitlements contain application group
  `2DC432GLL2.com.openai.sky.CUAService` (team `2DC432GLL2`), `app-sandbox =
  false`, and `com.apple.security.automation.apple-events = true`. The service
  shares the group; its IPC socket lives in the shared Group Container.
- The service updates itself through a dedicated Sparkle feed
  (`SUFeedURL: https://oaisidekickupdates.blob.core.windows.net/mac/cua/alpha/appcast.xml`,
  ed25519 pinned via `SUPublicEDKey`) — CUA ships and evolves independently of
  the host app.
- The service links AppKit, ApplicationServices, CoreGraphics, QuartzCore,
  AVFoundation, EventKit, Contacts, Intents, MapKit, IOKit (evidence: `otool
  -L SkyComputerUseService`).
- Swift modules visible in the string table: `ComputerUseCore`,
  `AccessibilitySupport` (types `AXUIElementProtocol`, `WindowUIElementProtocol`,
  `EditableTextObject`, `VirtualCursor`, `SystemFrontmostApplicationTracker`,
  `IdentifiableWindow`, `UIElementTreeTransaction.swift`), plus a
  `ComputerUse/RefetchableSkyshotAXTree.swift` source-path string.

## 2. Process model and IPC protocol

Reconstructed from `dist/project/cua/sky_js/src/targets/mac/native-pipe.js` and
`client.js` (readable JavaScript, exact):

- Transport: Unix domain socket at
  `~/Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/IPC/computeruse.sock`
  (overridable via `SKY_CUA_SERVICE_NATIVE_PIPE_PATH`).
- Framing: 4-byte little-endian payload length + UTF-8 JSON; hard cap 8 MiB
  (8388608 bytes) per frame.
- Dialect: JSON-RPC 2.0. Two methods:
  - `ping` — handshake: client sends `clientApiVersion`, server returns
    `serverApiVersion`; mismatch raises `incompatibleClientVersion`. Current
    version string: `CodexComputerUseIPC-5`.
  - `request` — envelope `{requestType, request, timeoutSeconds,
    deadlineUnixMilliseconds, codexTurnMetadata}`. `codexTurnMetadata` carries
    turn/call identity (`x-codex-turn-metadata` header value read from the
    `nodeRepl.requestMeta` host bridge: `call_id`, `item_id`).
- Request types (constants in `client.js`):
  `ComputerUseIPCListAppsRequest`, `ComputerUseIPCAppGetSkyshotRequest`,
  `ComputerUseIPCAppPerformActionRequest`, `ComputerUseIPCAppStartRequest`,
  `ComputerUseIPCAppPolicyRequest`, `ComputerUseIPCStartAudioRecordingRequest`,
  `ComputerUseIPCStopAudioRecordingRequest`, plus
  `ComputerUseIPCSkysightUpdateObservationPolicyRequest` (string table).
- "Skyshot" = the paired observation unit: accessibility tree text + window
  screenshot (`ComputerUseIPCSkyshot`, `ComputerUseIPCSkyshotResult`,
  `ComputerUseIPCScreenshot`, `RefetchableSkyshotAXTree`).
- Bootstrap (on socket connect failure): connect to the host bridge pipe
  (`NODE_REPL_HOST_SERVICES_PIPE_PATH`), send JSON-RPC `ensureService
  {service: "computer-use"}`; the host launches the service via LaunchServices
  (`openApplication` targeting bundle id `com.openai.sky.CUAService`,
  `$SKY_CUA_SERVICE_PATH`, or `$CODEX_HOME/computer-use/Codex Computer Use.app`),
  then the client retries the socket with a longer timeout (250 ms first pass,
  5 s after start). "Sky Computer Use requires the trusted nodeRepl runtime" —
  the transport is only reachable from the app's own `node_repl` host context.

## 3. Agent-facing tool surface

Three API generations ship side by side in `@oai/sky` (`docs/` + `src/types/`):

### 3.1 Window API (macOS, `target: "mac"`)

Operations: `list_apps`, `get_app_state` (AX text + screenshot,
diff-by-default), `click` (element_index or x/y, `mouse_button`, `click_count`,
`key` hold, `duration`), `press_key` (xdotool-style chords, `duration`),
`type_text`, `scroll` (element or coords, `direction`, `pages`), `set_value`,
`drag`, `perform_secondary_action` (named AX action), `paste` (text/md/html via
system pasteboard with prior-contents restore), `select_text` (match with
prefix/suffix disambiguation; `cursor_before`/`cursor_after` placement).

Documented workflow contract (from `SKILL.md`, both copies):

- Element-first: prefer `element_index` over coordinates; coordinates are the
  fallback when AX is unavailable.
- Observe-after-act: call `get_app_state` after actions; element indexes are
  only valid against the latest state.
- Diff output by default for token efficiency; `disableDiff` for a full tree.
- Auto-launch: `get_app_state` launches the app if not running.
- Auto-wait: ~1 s after an action before capturing state, extended up to 5 s
  while loading indicators are visible.
- Name/bundle-id duality: retry failed calls with the bundle id resolved from
  `list_apps()`.
- Screenshots are `file://` URLs the agent reads from disk; AX text is preferred
  over screenshots for cost, screenshots disambiguate when AX is incomplete.

### 3.2 Window2 API (Windows, `target: "windows"`)

Window-object addressing (`list_windows`/`get_window`), bounded screenshots
with `id/originX/originY/width/height/zIndex` (transient UI captured as
z-ordered stack), optional AX text, `activate_window` as explicit escape hatch.

### 3.3 Full-desktop API (Linux/X11, `target: "linux"`)

Adds `launch_app` (no shell), `activate_window`, `get_window_state(query=)` with
structured `AccessibilityNode {id, role, name, value, actions, states,
children, native_id}`, `move`/`move_relative`, `key_down`/`key_up` chord holds,
`drag_handle` (observe screenshots mid-drag before release), and
`clipboard_read`/`clipboard_release`/`clipboard_write` (snapshot handles that
invoke the app's own Copy/Paste actions). Targeted input never implicitly
activates windows.

## 4. Native engine evidence (SkyComputerUseService)

From the Swift string table (`strings` on the 24.5 MB binary):

- Accessibility: `AXUIElement`, `AXObserver`, `AXManualAccessibility`
  (private SPI to force-enable AX support in apps that lack it),
  `AccessibilitySPI`, `AXUIElementDestroyed`, key-window/frontmost-app
  tracking, `EditableTextObject` (select_text/set_value backing),
  `VirtualCursor`, `LMReadableElement`.
- Diff engine native-side: serialized tree rendering
  (`AccessibilityRenderingContext`, `AccessibilityTreePresentation`) with a
  line budget (`AccessibilityDifferenceLineBudgetExceeded`).
- Screenshots: ScreenCaptureKit (`SCStreamDelegate`, `SCStreamOutput`,
  `SCStreamFrameInfo`), plus CGWindow/QuartzCore paths.
- Input: `CGEvent` synthesis.
- App state: `FSMonitor`-style discovery + NSWorkspace-style running-app
  tracking (string evidence), `C UAServiceStatusItemView` menu bar presence.
- Audio capture: AVFoundation/AVFAudio recording with separate approval.
- Messaging/Calendar/Contacts: Apple Events + EventKit/Contacts frameworks;
  usage strings ("ChatGPT uses Contacts to show names and find phone numbers or
  email addresses for people you ask to message") indicate connector-level
  automation layered on the same service.
- Lock screen: `LockScreenLoginAuthorization.sock`; the Authorization Services
  plugin (`com.openai.sky.CUAService.AuthorizationPlugin`) verifies the socket
  peer via audit token + signing identifier + team identifier before honoring
  login-time authorization ("Login authorization socket peer is not the
  expected Codex Computer Use service").

## 5. Policy, approval, and telemetry model

From `targets/mac/computer-use-policy.js` (exact) and service strings:

- Every agent-facing call is wrapped: `withComputerUsePolicy(toolName, args,
  run)`. Sequence:
  1. Resolve app identity via the service (`ComputerUseIPCAppPolicyRequest`),
     receiving `allowed | denied | forbidden` for the target's bundle id.
     `denied` = blocked by organization policy; `forbidden` = blocked for
     safety reasons; both abort before any user prompt.
  2. HITL elicitation: "Allow Computer Use to use \"<App display name>\"?" with
     metadata `codex_approval_kind: mcp_tool_call`, `connector_id:
     "computer-use"`, `riskLevel` (from the target), optional warning
     subtitle, `tool_call_id` (from turn metadata), `tool_name`,
     `tool_params_display` (human-readable app name). Persistence options
     `["session", "always"]` when the target allows persistent approval.
  3. Parameter freezing: before execution the args object is rebuilt with
     non-writable, non-configurable property descriptors and `Object.freeze`;
     the `app` field is replaced by the policy-resolved `appPath`. The agent
     cannot swap the target between approval and execution.
  4. Telemetry: `approval_requested` / `approval_resolved
     {approvalResult: accepted|canceled|declined, approvalPersistence:
     session|always}` / `tool_called {bundleIdentifier, toolName, durationMs,
     terminalStatus: completed|cancelled|failed}`; `userStoppedSession` and
     `userIntervened` server error codes map to `cancelled`.
- Separate high-risk approval for audio recording
  (`requestComputerAudioApproval`, `riskLevel: "high"`, session-only).
- Approval-gated side effects downstream: send confirmation ("Message was not
  sent because the send was not approved") and read confirmation for withheld
  content ("Read access was not approved. No content was returned."), with
  explicit anti-fallback instructions telling the model not to route around a
  denial through Computer Use.
- URL-level policy checking exists service-side
  (`ComputerUseURLPolicyChecking`, `AuraSiteStatusURLPolicyChecker`,
  `PolicyCheckFailureBehavior`, `ComputerUseAllowForbiddenTargets`).
- Response metadata brands the turn surface: `codex/toolSurface
  {app, kind: appId|computerUse}` and a Chrome-specific marker
  (`codex/computerUseChrome`), consumed by the host UI.

## 6. Tool declaration to the model

`plugins/openai-bundled/plugins/computer-use/`:

- `.codex-plugin/plugin.json` v1.0.1001425 (locked to service build) with user
  interface copy, default prompts, and the governing instruction: "Prefer
  purpose-built connectors, APIs, or CLIs" — Computer Use is the fallback, not
  the default.
- `skills/computer-use/SKILL.md` (agent-facing): bootstrap
  `globalThis.sky = (await import("@oai/sky")).sky` inside the persistent
  `node_repl`; forbids AppleScript/osascript/JXA/System Events/CGEvent
  synthesis for app interaction (the library is the only sanctioned input
  path); full `Sky` type listing.
- The `messages` connector is exposed to the agent as an MCP server
  (`computer-use-client-launcher messages mcp`) — specialized connectors are
  MCP tools; Computer Use is a REPL-imported library.

## 7. Architectural summary

```
Model (agent loop)
  |
  |  skill bootstrap (import @oai/sky)
  v
node_repl (persistent JS runtime, trusted host bridge)
  |      ^
  |      |  elicitation / response meta (HITL, riskLevel, persist)
  v      |
withComputerUsePolicy  (JS side: freeze args, telemetry)
  |
  |  JSON-RPC 2.0 / UDS, 4B-LE framing, version handshake
  v
SkyComputerUseService (Swift, LSUIElement, own updater)
  |  policy provider (allowed/denied/forbidden, URL checks)
  |  AX engine: AXUIElement/AXObserver trees, AXManualAccessibility SPI,
  |             native diff rendering w/ line budget, EditableTextObject
  |  ScreenCaptureKit screenshots (skyshot = AX tree + image)
  |  CGEvent input synthesis; pasteboard management
  |  audio recording (separate approval); Apple Events connectors
  v
macOS (Accessibility TCC grant, Screen Recording TCC grant, Input Monitoring)
```

Distinguishing design choices worth copying:

1. Separately updatable service with a versioned IPC handshake.
2. Skyshot as an atomic observe unit (AX text + screenshot in one round trip).
3. Diff-by-default tree serialization with a line budget (token economics).
4. Element-index addressing valid only against the latest observation,
   enforced by agent-side workflow contract rather than protocol.
5. Three-state target policy (org-denied / safety-forbidden / allowed) checked
   before the user prompt; user approval never overrides a hard denial.
6. Argument freezing between approval and execution.
7. Three-layer telemetry: approval requested/resolved + tool call duration and
   terminal status, correlated by tool_call_id.
8. Specialized connectors (MCP) take precedence over Computer Use by policy.

## 8. Known unknowns

- Native-side internals (tree diff algorithm details, AX serialization format,
  ScreenCaptureKit stream configuration) are not decompiled; the JS layer and
  string tables bound the behavior but not the implementation.
- The `Skysight` observation-policy request and the telemetry transport are
  visible by name only.
- Runtime behavior (actual AX text format, timing constants in the service,
  Chrome-specific handling) is inferred from documented agent contracts, not
  observed live.
