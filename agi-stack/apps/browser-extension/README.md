# MemStack Browser Bridge

MV3 Chrome extension that lets the MemStack desktop app read and drive your
browser tabs. It is a thin CDP relay: the desktop sidecar (running in
`--native-host` mode) speaks JSON-RPC 2.0 to this extension over Chrome native
messaging; the extension translates that into `chrome.debugger` (CDP),
`chrome.tabs`, and debugger-event notifications.

All authentication and pairing is handled by the desktop app / broker. The
extension holds **no token** and has **no pairing UI** — the options page is a
read-only status view.

## Bridge contract (fixed)

- Transport: `chrome.runtime.connectNative('com.memstack.browserbridge')`.
- Requests (host → extension): `hello`, `ping`, `attach`, `detach`,
  `executeCdp` (10s timeout, auto-detach on timeout, error `code: 1`),
  `getTabs` (internal schemes excluded), `createTab` (background tab).
- Tab leases (host → extension):
  - `ensureTabGroup {key, title, color?} → {groupId}` — idempotent per key;
    the `key → groupId` mapping is persisted in `chrome.storage.local`
    (prefix `memstackTabGroup:`). A stale stored id (group closed) is
    recreated transparently. Creating a group needs an anchor tab, so a
    background `about:blank` placeholder tab is created for a fresh group.
  - `assignTab {tabId, groupId} → {}` — `chrome.tabs.group`; a missing or
    invalid `groupId` is reported as `-32602`.
  - `ungroupTab {tabId} → {}`, `closeTab {tabId} → {}` (debugger detached
    first, best-effort), `focusTab {tabId} → {}` (activates the tab, never
    focuses the window).
  - `moveMouse {tabId, x, y, waitForArrival?=true} → {}` — virtual cursor,
    see below.
  - `turnEnded {leases:[{tabId, origin, mark?}]} → {closed, ungrouped}` —
    turn cleanup: unmarked agent tabs close, `deliverable` tabs are
    ungrouped but kept, `handoff` tabs stay in their group, user tabs are
    untouched. Per-tab failures are tolerated; only successes are counted.
- Notifications (extension → host): `onCDPEvent`, `onCDPDetach`.
- Errors: JSON-RPC `{code, message}`; `-32601` unknown method, `-32602`
  invalid params.
- Kill-switch: when the native port disconnects, every attached debugger is
  detached immediately and all virtual-cursor state is cleared, then
  reconnect is scheduled via `chrome.alarms`
  (`native-reconnect` every 30s, `native-reconnect-fast` after ~5s).

## Virtual cursor

`moveMouse` gates the real CDP `Input` dispatch on the *visual* arrival of a
fake cursor (design §2.7), and doubles as an action throttle:

- The SW checks observability first: the tab must be the active tab of a
  normal, non-minimized window. Unobserved tabs (or `waitForArrival:false`,
  e.g. drags) publish `{animateMovement:false}` (teleport) and return
  immediately — no arrival wait.
- Observed moves create an arrival waiter keyed `${tabId}:${moveSequence}`
  (monotonic per SW) with a 1500ms timeout, publish the state, and await the
  waiter. The publish itself has a 1000ms breaker; a publish failure resolves
  the waiter at once. Every path resolves — the handler never hangs.
- Publishing ensures the cursor content script
  (`entrypoints/cursor.content.ts`, built to `content-scripts/cursor.js`) is
  injected on demand: a `AGENT_CURSOR_PING` message is tried first and
  `chrome.scripting.executeScript` only runs when the ping fails. The script
  is then driven with `AGENT_CURSOR_STATE` messages and reports back
  `AGENT_CURSOR_ARRIVED {moveSequence}`. The page side is stateless — the SW
  holds the last state per tab and answers `GET_AGENT_CURSOR_STATE` pulls
  (initial load + bfcache `pageshow`).
- Overlay: closed shadow root on `document.documentElement`, `position:fixed;
  inset:0; z-index:2147483646; pointer-events:none`, hidden for print, top
  frame only, re-appended by a MutationObserver if the page removes it.
  Coordinates are viewport CSS pixels (same space as CDP Input — no dpr or
  scroll math anywhere).
- Animation engine (`src/cursor/engine.ts`, framework-free and unit-tested):
  SwiftUI-style `{response, dampingFraction}` springs integrated with
  semi-implicit Euler at fixed 240Hz substeps under rAF. Moves ≤196px
  "scoot" (direct spring + `sin(π·progress)` dip/tilt); longer moves pick
  the cheapest of 20 candidate bezier paths (2 plain cubics + 18 two-segment
  arcs) scored by `length + overshoot·320 + angleChangeEnergy·140 +
  maxAngleChange·180 + totalTurn·18 + backtrack·90 + (arc?45:0)` sampled at
  24 points/segment against a 20px viewport margin. Path progress is itself
  a spring (response clamped to [0.12s, 2.2s]) with the position spring
  trailing it. Speed-adaptive stretch `clamp(1−speed/5500, .65, 1)` along
  the heading, resting orientation −44°, arrival at progress ≥.999 AND
  ≤0.85px AND ≤12px/s, then a 1.4s rotation wobble.
- Turn/lease integration: `turnEnded` hides the cursor on affected tabs;
  native-port disconnect clears all cursor state.

## Foreign-frame monitor

`entrypoints/foreign-frame-monitor.content.ts` (document_start, all frames,
injected programmatically via `ensureMonitorInjected(tabId)` from the
`assignTab` / `createTab` claim paths) walks the DOM — including open and
closed shadow roots (`chrome.dom.openOrClosedShadowRoot` when available) —
plus a MutationObserver, and neutralizes any `<iframe>`/`<frame>` whose src
is a `chrome-extension://` URL of a *different* extension id by blanking it
(`src="about:blank"`, srcdoc cleared). Core logic lives in `src/monitor.ts`
and is unit-tested with fake DOM trees.

## Build

```bash
pnpm install
pnpm build
```

Load unpacked from `.output/chrome-mv3` in `chrome://extensions` (Developer
mode → "Load unpacked"). The extension ID is pinned by the manifest `key` and
must be:

```
enbljdpbhdllbbkcjhccmbgpkfmcdkkl
```

If the ID differs, the `key` in `wxt.config.ts` was altered — restore it.

## Native host registration

No manual step. The desktop app registers the native messaging host manifest
for `com.memstack.browserbridge` (pointing at the sidecar binary's
`--native-host` mode) against the pinned extension ID at install/first-run
time.

## Dev loop

- `pnpm dev` — WXT dev mode with auto-reload into a scratch browser profile.
- `pnpm build` — production build to `.output/chrome-mv3`.
- `pnpm test` — Vitest unit tests (dispatcher, param validation, tab-group
  leases, turnEnded cleanup, moveMouse handshake + breakers, cursor engine
  math, foreign-frame monitor, kill-switch, reconnect scheduling, event
  relay) against a hand-rolled `chrome.*` mock.
- `pnpm test:snapshot` — Playwright harness that evaluates
  `assets/snapshot.js` against a fixture page (forms, shadow DOM, iframe,
  hidden elements, truncation) and asserts the snapshot shape.
- `pnpm test:bridge` — live end-to-end smoke: spawns the real sidecar
  (debug build, override with `AGISTACK_SIDECAR_PATH`), enables the bridge,
  installs the native messaging manifest, launches a headed Playwright
  Chromium with this extension loaded, and asserts the broker connects and
  all four `browser_*` tools appear in `/mcp/tools/list`. Cleans up after
  itself (manifest uninstalled, throwaway profile deleted).
  Note: branded Google Chrome blocks `--load-extension`, and Chromium
  resolves the user-level `NativeMessagingHosts` directory relative to the
  active user-data-dir — the smoke mirrors the manifest into its throwaway
  profile for that reason. Real Chrome usage with the default profile reads
  the system install and needs neither workaround.

After changing code, reload the extension in `chrome://extensions` (or let
`pnpm dev` handle it).

## Layout

- `entrypoints/background.ts` — service worker; wiring only.
- `entrypoints/cursor.content.ts` — virtual-cursor content script (injected
  on demand by the SW, not manifest-registered).
- `entrypoints/foreign-frame-monitor.content.ts` — foreign-extension iframe
  neutralizer (injected into leased tabs, all frames).
- `entrypoints/options/` — read-only status page (connection state from
  `chrome.storage.local`).
- `src/protocol.ts` — JSON-RPC 2.0 types, error codes, param validation.
- `src/handlers.ts` — method handlers + `attachedTabs` bookkeeping.
- `src/tab-groups.ts` — `key → groupId` registry (storage-persisted).
- `src/cursor/engine.ts` — spring/bezier cursor animation engine (pure TS).
- `src/cursor/overlay.ts` — shadow-DOM cursor overlay + SVG asset.
- `src/cursor/cursor-manager.ts` — SW half of the cursor handshake.
- `src/monitor.ts` — foreign-frame monitor core + SW injector.
- `src/transport.ts` — native-port state machine, kill-switch, reconnect,
  event relay.
- `assets/snapshot.js` — in-page accessibility snapshot script (evaluated via
  CDP `Runtime.evaluate`). Mirrored into
  `agi-stack/crates/adapters-browser/assets/snapshot.js` — keep the two copies
  byte-identical.
- `scripts/test-snapshot.mjs` + `scripts/fixtures/` — snapshot harness.
- `tests/` — Vitest suites.
