# Desktop QA Log

## 2026-07-09

### Verified

- `make run-desktop` launches the Tauri dev shell, starts Vite on `127.0.0.1:5173`,
  and renders the React app to `New session`.
- Browser QA on `http://127.0.0.1:5173` verifies the signed-out desktop shell,
  sign-in dialog, successful local login against `http://127.0.0.1:8000`,
  workspace chat entry, and sending a workspace task prompt.
- Sign-in defaults to the currently available MemStack Python API on `:8000`.
- The sign-in dialog no longer displays the local development password in visible
  helper text; local presets still fill the session-only test account.
- Desktop favicon now resolves through a real `public/favicon.svg`, eliminating
  the browser 404 noise during page load.
- The desktop window now shows a single native macOS traffic-light control set.
  The duplicated in-app traffic-light row is not present in the accessibility tree
  or screenshot.
- GitHub Copilot reference window confirms the target chrome pattern: native
  traffic lights, one app titlebar row, left sidebar, central timeline, right
  workspace panel, and bottom composer.
- A fresh GitHub Copilot.app Computer Use capture confirms the detailed target
  layout: 220px sidebar, Quick links, Sessions, central conversation timeline
  with run/tool cards, bottom workflow chips, and a right Workspace panel with
  tabbed review content.
- Rebuilt release macOS bundle was captured through Computer Use by targeting
  `src-tauri/target/release/bundle/macos/agi-stack Desktop.app`; the native app
  exposes the current signed-out workflow shortcut set and warning/composer UI.
- Local server smoke on `http://127.0.0.1:8000` confirms the default admin
  account can log in, tenants/projects/workspaces load, workspace messages can
  be created, a real Agent conversation can be created and linked to a
  workspace, and `/api/v1/agent/ws` returns `ack/send_message` without
  `Conversation not found`.

### Fixed

- Reordered local development server presets so the default login path uses the
  running `:8000` API while keeping the Rust `:8088` preset available.
- Replaced visible local password helper copy with non-secret preset guidance.
- Added a real Vite/Tauri favicon asset and source link.
- Removed visible in-app fallback window-control classes from the desktop shell
  and boot fallback.
- Kept the Tauri main window on the standard visible native titlebar.
- Added `core:window:allow-start-dragging` so `data-tauri-drag-region` does not
  fail the app at startup.
- Matched the desktop sidebar width to the GitHub Copilot reference window's
  220px sidebar, preserving the same collapsed width.
- Exposed the signed-out session workflow chips so the landing workspace matches
  the GitHub Copilot shortcut set: changes, PR, plan, background, and artifacts.
  The five chips fit inside the strip without clipping.
- Restyled signed-out workflow shortcuts from a single visible strip into
  individual dark pills, matching the GitHub Copilot composer shortcut pattern.
- Replaced the desktop Agent WebSocket send path's synthetic
  `workspace:<id>`/`project:<id>` conversation IDs with a real
  `/api/v1/agent/conversations` session, linked through the existing
  conversation mode endpoint when a workspace is selected.
- Added required `project_id` values to status and lifecycle WebSocket
  subscriptions so the desktop socket matches both Python and Rust server
  contracts.
- Added the same five workflow chips to the signed-in Chat composer and wired
  them to the right-side workspace review panel without navigating the center
  chat timeline away from Chat.
- Fixed Chat composer Background and Artifacts shortcuts so they make their
  hidden Workspace review tabs visible and show the correct right-panel content.
- Moved the signed-in Chat composer controls below the message input so the
  order matches the signed-out composer and GitHub Copilot reference.
- Split workspace message persistence from Agent launch in the send path: once
  the workspace message is saved, the composer clears even if Agent startup later
  reports a separate error.
- Fixed the Background agents panel to show the newest socket events first
  instead of the oldest events.
- Added center-timeline `Agent task` status cards after Chat sends a workspace
  message, matching the GitHub Copilot pattern where task/run feedback appears
  in the conversation timeline rather than only in a side panel.
- Wired Agent task cards to live socket events: `ack/send_message`,
  `user_message`, and `message` move the card to `Accepted`; socket error
  events move it to `Needs attention` and show the backend error detail when
  provided.
- Added Chat auto-scroll for new messages, task status transitions, and window
  resize so the latest Agent task card remains visible after desktop-to-mobile
  viewport changes.
- Made Chat disabled-state reasons more diagnostic: missing account/project now
  shows `Select an account and project before chatting.` instead of a generic
  workspace connection message.
- Removed the optional sandbox status GET from ordinary runtime refresh. This
  avoids browser console 404 noise when a project has no sandbox yet; explicit
  Sandbox/Terminal actions still create/start/sync sandbox state.
- Removed the same optional sandbox status GET from `DesktopApiClient.loadRuntime()`
  so future bulk runtime loads do not reintroduce project sandbox 404 noise.
- Fixed Chat's grid rows so header, scroll timeline, and composer are three
  explicit rows; mobile task cards no longer slide under the composer.
- Shortened the mobile composer effort label from `Medium` to `Med` in compact
  mode so the control text no longer clips at 390px width.
- Renamed the command palette dialog from `Search commands` to
  `Command palette`, leaving `Search commands` only on the input. This removes
  an accessibility-name collision that affected screen-reader and automation
  targeting.
- Changed the HTML favicon href to `/favicon.svg` for stable dev-server
  resolution.
- Added a Copilot-like `Add workspace tab` action to the right Workspace panel.
  The `More tabs` menu now contains only overflow tabs, while `Add workspace tab`
  exposes all review surfaces: Changes, Pull request, Plan, Terminal,
  Background agents, and Artifacts.
- Fixed default desktop workspace creation. The previous payload used invalid
  or over-specific workspace metadata for the running Python API, first causing
  `422` and then `400 Invalid workspace request` because a software-development
  workspace requires `sandbox_code_root`. Desktop now creates timestamped
  conversation workspaces with `multi_agent_shared` collaboration so repeated
  New session clicks do not collide or require a code root.
- Fixed the local-development sign-in modal so the default selected MemStack
  `:8000` preset primes the session-only test account as soon as the dialog
  opens. The visible selected preset and the enabled `Login` action now agree.
- Changed successful password login with a project to land directly in Chat,
  matching the GitHub Copilot session flow where the user can immediately
  message the Agent and start a task instead of first seeing a dashboard.
- Replaced the signed-in Sessions sidebar's flat workspace list with a
  Copilot-like hierarchy: `Chats`, the selected project root, `New session in
  <project>`, and project-scoped session children.
- Changed successful workspace/session creation to land directly in Chat so a
  newly created session is immediately ready for Agent messages instead of
  detouring through the Workspace overview.
- Updated the signed-in Sessions root label to follow the grouping mode:
  project grouping shows the project root, while `Recent first` shows `Recent
  sessions` with the selected project context.
- Ensured the Tauri main window is also created during setup, leaving
  `RunEvent::Ready` and macOS reopen handling as fallback window restoration
  paths.
- Removed the extra signed-in `Tools` sidebar group so the left navigation now
  matches the GitHub Copilot structure: Quick links, Sessions, then the bottom
  account/settings area. Tool surfaces remain reachable through command
  routing, the right Workspace panel, and bottom settings.
- Added the missing signed-in `New chat` row under `Chats`, matching the
  GitHub Copilot Sessions hierarchy while reusing the existing workspace-backed
  new-session creation path.
- Changed the signed-in Chat composer to submit through a real form. `Enter`
  now sends the task, `Shift+Enter` preserves multiline input, and the send
  button uses the same guarded submit path.
- Fixed Agent task status attribution for multiple tasks in the same
  conversation. Socket updates now match `message_id` when present and otherwise
  update only the latest matching task card, preventing a later conversation
  error from flipping older accepted cards to `Needs attention`.
- Broadened Agent socket error parsing so nested `payload`, `data`, or `error`
  objects can surface their concrete message in the task card instead of only a
  generic error label.
- Replaced the composer send affordance's rocket glyph with a green circular
  up-arrow in both signed-out and signed-in composers, matching the GitHub
  Copilot message input affordance more closely while leaving the send action
  semantics unchanged.
- Replaced the signed-in Chat composer's visible `Connected` footer text with a
  fixed-size status dot that keeps the accessibility label and tooltip while
  matching GitHub Copilot's compact message-input control cluster more closely.
- Aligned the signed-in Chat composer's model selector with the signed-out
  composer and GitHub Copilot reference by showing `Claude Fable 5 · 1M`
  instead of the generic `Local model` label.
- Aligned the signed-in Chat composer's empty prompt with the GitHub Copilot
  task-entry copy so logged-in users see `Describe a task to run autonomously`
  instead of the generic `Message this workspace` placeholder.
- Changed the Workspace Artifacts tab from raw event JSON dumps into a
  Copilot-like artifact surface with filter chips, search, empty-state copy,
  and derived artifact rows from timeline, socket event, and plan artifact
  metadata.
- Wired the signed-in Chat composer workflow badges to live background event
  and artifact counts instead of static `0` placeholders.
- Changed the Workspace Background agents tab from raw JSON dumps into a
  filterable/searchable event stream with event categories, row summaries,
  readable nested sandbox artifact details, and collapsible raw payloads.
- Replaced the Workspace Changes empty state with a Copilot-like Human decision
  review surface. The panel now derives requester, risk, changed-file count,
  diff summary, agent reasoning, and context metrics from the loaded workspace
  tasks, events, plan, and artifacts, then records local Approve / Request
  changes decisions with a visible history.
- Added the missing Tool events parity controls to the Workspace Background
  agents tab: an Auto-scroll toggle that keeps the newest event set in view and
  a Clear action that resets event filter/search scans back to `All`.
- Added the missing web-parity controls to the Workspace Artifacts tab:
  `Artifact sort` with Recent first / Largest first / Name options, plus a
  list/grid toggle that switches the artifact surface layout state.
- Fixed Artifacts extraction for nested socket events so `payload.type` /
  `payload.data.type` artifact lifecycle events populate the Workspace
  Artifacts tab instead of appearing only in Background agents. Artifact rows
  now dedupe `created` / `ready` lifecycle pairs by `artifact_id`, prefer the
  richer `ready` state, support row selection, show a trailing row actions
  affordance, and include a footer with visible item count, total size, and
  selected artifact name.
- Added the missing Tool events row-selection parity to the Workspace
  Background agents tab. Event rows now behave as selectable buttons with
  `aria-pressed`, a latency slot, trailing chevron, selected-row styling, and a
  footer that reports the visible event count, active filter/search scope, and
  selected event type while preserving collapsible raw payload details.
- Replaced the Workspace Pull request tab's empty-state-only view with a
  derived local PR packet. The tab now summarizes branch/base/diff metadata,
  files changed, estimated risk, check status, file artifacts, recent activity,
  and local review actions, with shortcuts back to Changes and Artifacts.
- Added web Run graph parity controls to the desktop Board: memory scope,
  agent layout, zoom, view, task filter, and state chips. The shared filter now
  drives both Flow and List tasks, List shows an empty-state when scoped out,
  and the Board shell uses explicit rows so the toolbar stays under the header.
- Added web topbar run-control parity to the signed-in desktop shell: visible
  run state chip, Pause/Resume, Stop, Runtime target, and Live/Offline controls.
  The Run action now mirrors the prototype run control by starting/resuming the
  selected run and restoring live updates without leaving the current Board
  surface; connection refresh still runs only when the workspace is not ready.
- Aligned the desktop Quick links with the web prototype's primary navigation:
  Runs, Agents, Memory, Artifacts, and Runtime. Runs opens the Board run graph,
  Agents opens Workspace Background agents, Memory opens the memory status tab,
  Artifacts opens the Workspace Artifacts tab, and Runtime opens connection
  settings. The same entries are available from the compact mobile section menu.
- Added the web-parity Runs list to the signed-in/manual desktop sidebar. The
  list prefers recent Agent conversations, falls back to workspace rows, and
  finally shows the current session; selecting a row opens the Board run graph
  while Pause/Resume/Stop state is preserved per selected run row.
- Preserved saved run states in the sidebar even when a run is not selected.
  Non-selected local rows now keep Planning/Paused/Stopped labels and dot
  tones, while data-backed active/completed/failed statuses map to
  prototype-style Running/Completed/Failed labels and green/red tones.
- Added the web-parity `Create new run` control to the desktop Runs list. The
  control creates local draft run rows, selects the newest run, places it at the
  top of the list, and opens the Board without calling the workspace/session
  creation API.
- Added prototype-parity local run queue events for `Create new run`. Creating
  a local draft run now adds a client-side `message` event from `System`,
  `New run #<n> queued with local runtime.`, and the Runtime Monitor event
  count, Workspace Background agents tab, and Human decision review packet all
  read from the merged local + socket event stream.
- Fixed Workspace Background agents event ordering by reading nested socket
  payload ISO timestamps before falling back to current time. Local run queue
  events now sort predictably against real socket events instead of being pushed
  behind older events that lacked a top-level timestamp.
- Updated the Board run-context titlebar to mirror the selected run, so run
  surfaces show `Run: <selected run>` while non-run runtime areas continue to
  show the current session title.
- Added command-bar runtime target parity to the desktop Chat composer. The
  composer now exposes the same Local Rust Core / Remote staging target switch
  as the web prototype command bar and keeps it synchronized with the titlebar
  runtime selector.
- Added command-bar slash command parity to the desktop Chat composer. The
  signed-in/manual composer now has a `/` button matching the web prototype's
  slash command affordance and opens the existing Command palette without
  duplicating command logic.
- Added topbar `More run actions` parity for the selected run. The overflow
  menu exposes Pause/Resume, Stop, Run selected session, Refresh workspace, and
  Open chat actions while preserving the existing disabled states for
  unconfigured manual runtimes.
- Added sidebar `Runtime monitor` parity under Runs. The card summarizes the
  active runtime target, connection state, live-update state, scope, event
  count, and queued task count, then routes `Open Runtime Monitor` back to
  Runtime settings without adding fake host CPU or memory telemetry.
- Aligned the Runtime monitor badge with the web prototype's health language.
  The card now displays user-facing Healthy/Starting/Waiting/Offline/Error
  states derived from real connection and live-update state instead of exposing
  raw internal connection enum values.
- Added topbar run time chip parity. The desktop titlebar now mirrors the web
  prototype's run clock affordance with a compact clock chip next to run state,
  backed by the selected run's real timestamp or the current `lastSync` label.
- Added Board run-graph time scale parity. Flow mode now shows the prototype's
  00:00 → 00:30 scale with a visible `Now` marker between the board state chips
  and lane grid, while List mode keeps its existing task table.
- Connected the Human decision review actions to the selected run state when
  `Apply to this run only` is checked. `Request changes` now pauses the selected
  run, `Approve` returns it to Running, and workspace-packet scope keeps the
  review decision local without changing run state.
- Changed the Board Flow view to render Timeline and Swimlane tasks as
  time-positioned task pills instead of ordinary lane cards. Existing workspace
  task data remains authoritative; optional `metadata.timeline_left` and
  `metadata.timeline_width` values control exact task placement when present.
- Changed the Human decision review packet to follow the currently selected
  Board task first. Clicking a Timeline or Swimlane task pill now updates the
  Workspace Changes review title, summary, requester/risk context, and local
  decision actions for that selected task instead of always reviewing the first
  or blocked task.
- Added prototype-parity Board task selection events. Clicking a Timeline,
  Swimlane, Compact, or List task now appends a local `selection` event into
  the merged Background agents stream with the selected task, board mode, run,
  project, and workspace metadata.
- Aligned the Background agents `Clear` action with the prototype Tool events
  clear behavior. The button now clears local interaction events, including
  local run queue and task selection events, while preserving real socket events
  and still resetting any active event filter/search.
- Added prototype-parity Human decision events. `Approve` and `Request changes`
  now append local `decision` events to Background agents with the selected
  run, task, project, and workspace metadata while preserving the existing
  local decision history and run-state updates.
- Aligned prototype custom event filter semantics. Local `decision` and
  `selection` interaction events now count under the Background agents
  `Messages` filter, matching the web prototype's default `addEvent(...,
  type = "Messages")` behavior instead of falling through to `System`.
- Added prototype-parity Operator message events for Board command submissions.
  Submitted Board run commands now append a local `message` event from
  `Operator` before continuing through the existing workspace/Agent send path,
  and local `message` details are preserved instead of being collapsed to the
  generic payload type.
- Added a Workspace review panel close control that matches the web prototype's
  Human decision drawer close affordance. The in-panel close button reuses the
  existing `reviewPanelOpen` state, collapses the workbench layout, and leaves
  the topbar `Show workspace panel` control as the restore path.
- Changed local draft runs to start in `Planning`, matching the web prototype's
  `Create new run` flow. Planning exposes `Pause`; pausing moves the selected
  run to `Paused` / `Resume`, and resuming moves it to `Running` / `Pause`.
- Added the web prototype's bottom run command bar to the Board surface. Runs >
  Board now exposes Slash commands, a `Steer this run or start a new task...`
  input, prototype model choices, the synchronized Runtime target selector, and
  a green send affordance that reuses the existing workspace message / Agent
  task send path.
- Aligned the Board `Memory scope` control with the web prototype's run-isolated
  label. The first scope option now follows the selected run, for example
  `Run #1 (isolated)`, and the Board state chips use the same selected-run
  scope text instead of the generic `Workspace isolated`.
- Added the web prototype's independent topbar `Resume` control next to the
  existing Pause/Resume toggle. The direct Resume action returns Planning or
  Paused runs to Running, restores live updates, and disables itself once the
  selected run is already Running.

### Validation

- `pnpm run build`
- Playwright edge suite on `http://127.0.0.1:5173`:
  `signed-out -> sign in -> Use MemStack :8000 -> Login -> Chats -> empty send
  disabled -> Send workspace message -> Agent task card accepted -> clear
  Project ID -> Chat disabled with project-specific reason -> restore project
  -> mobile viewport`.
- Final Playwright edge suite result: no failures, no console logs, no 404
  responses. Screenshots: `/tmp/agi-desktop-agent-card.png`,
  `/tmp/agi-desktop-missing-project.png`, `/tmp/agi-desktop-mobile.png`.
- Latest Playwright edge suite result: no failures, no actionable console
  warnings/errors, and no 404 responses for
  `signed-out workflow pills -> sign in -> Chats -> Background/Artifacts review
  tab switching -> send Agent task -> mobile task-card layout -> missing Project
  ID disabled state -> restore project`. Screenshots:
  `/tmp/agi-desktop-signed-out-pills.png`, `/tmp/agi-desktop-agent-card.png`,
  `/tmp/agi-desktop-mobile-agent-card.png`, and
  `/tmp/agi-desktop-missing-project.png`.
- Focused Playwright check confirms Chat composer Background/Artifacts chips
  surface their corresponding Workspace review tabs. Screenshot:
  `/tmp/agi-desktop-review-overflow-tabs.png`.
- Focused mobile Playwright check confirms the compact composer controls render
  complete labels at `390x844`, including `Effort selector, Medium` displayed
  as `Med`. Screenshot: `/tmp/agi-desktop-mobile-composer-controls.png`.
- Browser plugin smoke confirms `http://127.0.0.1:5173/` has the expected
  title, non-empty signed-out content, five workflow shortcuts, no framework
  error overlay, and no console warnings/errors.
- Browser plugin command-palette probe found the `Search commands` accessible
  name collision. After the fix, Browser verifies that the input is unique,
  selecting the `api` command switches into manual API-key mode, and focus lands
  on the API key field.
- Playwright command-palette edge suite verifies signed-out command search to
  API-key settings, login error against the known-down `:8088` preset, signed-in
  `Meta+K -> chat -> Enter` navigation, and the no-results state. Screenshots:
  `/tmp/agi-desktop-command-palette-api-key.png`,
  `/tmp/agi-desktop-login-error-8088.png`,
  `/tmp/agi-desktop-command-palette-chat.png`, and
  `/tmp/agi-desktop-command-palette-empty.png`. The only console entry is the
  expected `ERR_CONNECTION_REFUSED` from intentionally testing the unavailable
  `:8088` login preset.
- Playwright mobile entry suite verifies the signed-out `Session actions` menu,
  API-key fallback focus, mobile settings layout, and mobile sign-in modal
  without horizontal overflow or password literal leakage. Screenshots:
  `/tmp/agi-desktop-mobile-session-actions.png`,
  `/tmp/agi-desktop-mobile-api-key.png`, and
  `/tmp/agi-desktop-mobile-login-modal.png`.
- Playwright Workspace tab suite verifies `More tabs` only lists Background
  agents and Artifacts, `Add workspace tab` lists all six review tabs, and
  selecting Artifacts syncs the right panel without console or network errors.
  Screenshots: `/tmp/agi-desktop-workspace-more-tabs.png` and
  `/tmp/agi-desktop-workspace-add-tab-artifacts.png`.
- Playwright session/logout suite verifies signed-in session grouping, `Run`
  routing into Chat, timestamped workspace creation with a new selected
  workspace id, and logout returning to the signed-out New session composer with
  signed-in tools removed. Screenshot:
  `/tmp/agi-desktop-session-logout-regression.png`.
- Playwright login-to-Agent suite verifies the sign-in dialog opens with the
  default local preset already enabled, login lands directly in Chat, and a
  workspace message creates an `Agent task` card that reaches `Accepted` without
  console or network errors. Screenshots:
  `/tmp/agi-desktop-login-preset-enabled.png`,
  `/tmp/agi-desktop-login-auto-chat.png`, and
  `/tmp/agi-desktop-login-chat-task.png`.
- Mobile Agent task card regression at `390x844`: no horizontal overflow, right
  review panel hidden, Agent task card visible inside the message scroll area,
  and no overlap with the composer. Screenshot:
  `/tmp/agi-desktop-mobile-agent-card.png`.
- Browser plugin Artifacts tab QA verifies manual-key entry, Workspace Add tab
  routing into Artifacts, the visible filter/search controls, `Patches` filter
  selection, search value persistence, empty-state copy, no framework overlay,
  and no console warnings/errors. Screenshot:
  `/tmp/agi-desktop-artifacts-tab.png`.
- Browser plugin mobile smoke at `390x844` verifies no page-level horizontal
  overflow, the Workspace review panel remains hidden per mobile rules, and
  no console warnings/errors. Screenshot:
  `/tmp/agi-desktop-artifacts-mobile.png`.
- Browser plugin Background agents QA verifies a real signed-in workspace with
  80 live events, scoped `Messages` filter + `message` search empty-state
  behavior, scoped `Tools` filter + `sandbox` search event rows, readable
  `artifact_ready` / `artifact_created` summaries, no framework overlay, and
  no console warnings/errors. Screenshot:
  `/tmp/agi-desktop-background-tools-filter.png`.
- agent-browser mobile smoke at `390x844` verifies no page-level horizontal
  overflow, the Workspace review panel remains hidden per mobile rules, and no
  page errors. Screenshot: `/tmp/agi-desktop-background-mobile.png`.
- agent-browser Changes tab QA verifies a real signed-in workspace with 80
  background events and 12 plan fields renders the Human decision review,
  clicking `Approve` changes the state to `Decision recorded / Approved`, then
  clicking `Request changes` changes the state to `Changes requested` and keeps
  both local decision history rows. Console output only contains Vite/React dev
  info and `agent-browser errors --json` reports no page errors. Screenshot:
  `/tmp/agi-desktop-decision-review.png`.
- agent-browser mobile smoke at `390x844` verifies no page-level horizontal
  overflow, no Vite error overlay, and the Workspace review panel remains
  hidden per mobile rules. Screenshot:
  `/tmp/agi-desktop-decision-mobile.png`.
- agent-browser Background agents controls QA verifies a real signed-in
  workspace with 80 live events renders the new `Auto-scroll` and `Clear`
  controls, `Clear` starts disabled, `Tools` + `sandbox` filtering enables it,
  clicking `Clear` restores the empty search and disables it again, and the
  Auto-scroll toggle updates `aria-pressed` from `true` to `false`. Console
  output only contains Vite/React dev info and `agent-browser errors --json`
  reports no page errors. Screenshot:
  `/tmp/agi-desktop-background-controls.png`.
- agent-browser Background controls mobile smoke at `390x844` verifies no
  page-level horizontal overflow, no Vite error overlay, no page errors, and
  the Workspace review panel remains hidden per mobile rules. Screenshot:
  `/tmp/agi-desktop-background-controls-mobile.png`.
- agent-browser Artifacts sort/grid QA verifies a real signed-in workspace can
  open the Artifacts tab, sees `Artifact sort` and the grid/list toggle, changes
  sorting from `recent` to `largest`, and toggles the view button from
  `aria-pressed=false` / `Switch artifacts to grid view` to
  `aria-pressed=true` / `Switch artifacts to list view`. The workspace had zero
  artifact rows, so this validates controls and empty-state behavior rather
  than non-empty row ordering. Console output only contains Vite/React dev info
  and `agent-browser errors --json` reports no page errors. Screenshot:
  `/tmp/agi-desktop-artifact-sort-grid.png`.
- agent-browser Artifacts sort/grid mobile smoke at `390x844` verifies no
  page-level horizontal overflow, no Vite error overlay, no page errors, and the
  signed-in workspace remains reachable. Screenshot:
  `/tmp/agi-desktop-artifact-sort-grid-mobile.png`.
- agent-browser Artifacts extraction/selection QA verifies the real signed-in
  `Desktop workspace 2026-07-09 16:11:06` workspace now renders 39 deduped
  artifact rows from nested artifact socket events, selects one artifact by
  default, changes selection from `01_loaded.png` to `02_no_composer.png` with
  exactly one `aria-pressed=true` row, and shows footer text
  `39 items / Total 879.6 KB / Selected 02_no_composer.png`. Sorting to
  `largest` and switching to grid view update the select value, grid class, and
  view-toggle label. Console output only contains Vite/React dev info and
  `agent-browser errors --json` reports no page errors. Screenshot:
  `/tmp/agi-desktop-artifact-select-footer.png`.
- agent-browser Artifacts extraction mobile smoke at `390x844` verifies no
  page-level horizontal overflow, no Vite error overlay, no page errors, and the
  signed-in workspace remains reachable. Screenshot:
  `/tmp/agi-desktop-artifact-select-footer-mobile.png`.
- Browser plugin navigation to the local Vite app timed out in this pass and
  reset its session, so the rendered QA fell back to `agent-browser`.
  agent-browser Background event selection QA verifies the real signed-in
  `Desktop workspace 2026-07-09 16:11:06` workspace with 80 events selects one
  row by default, moves selection to the second row with exactly one
  `aria-pressed=true` row, keeps raw event details available, shows the latency
  slot and chevron, and updates the footer to `78 events / Tools / artifact /
  Selected sandbox_event` after filter/search. Console output only contains
  Vite/React dev info and `agent-browser errors --json` reports no page errors.
  Screenshot: `/tmp/agi-desktop-background-select-footer.png`.
- agent-browser Background event selection mobile smoke at `390x844` verifies
  no page-level horizontal overflow, no Vite error overlay, no page errors, and
  the compact Background tab remains reachable while the Workspace review panel
  stays hidden per mobile rules. Screenshot:
  `/tmp/agi-desktop-background-select-footer-mobile.png`.
- Browser plugin navigation to the local Vite app timed out again in this pass
  and reset its session, so rendered QA fell back to `agent-browser`.
  agent-browser Pull request panel QA verifies the signed-in
  `Desktop workspace 2026-07-09 21:39:01` workspace renders a derived PR packet
  with status `ready to review`, branch `workspace/da8462ea`, diff `+0 -0`,
  5 changed files, Medium risk, 4 check rows, 5 file rows, 4 activity rows, and
  enabled Approve / Request changes actions. `Open artifacts` routes to the
  Artifacts tab with 39 rows and the expected footer, while Approve followed by
  `Open review` routes to Changes and shows `Decision recorded / Approved`.
  Console output only contains Vite/React dev info and
  `agent-browser errors --json` reports no page errors. Screenshots:
  `/tmp/agi-desktop-pr-review-panel.png` and
  `/tmp/agi-desktop-pr-review-panel-files.png`.
- agent-browser Pull request mobile smoke at `390x844` verifies no page-level
  horizontal overflow, no Vite error overlay, no page errors, and the compact
  `PR idle` chip remains reachable while the Workspace review panel stays hidden
  per mobile rules. Screenshot: `/tmp/agi-desktop-pr-review-mobile.png`.
- Browser fallback Playwright smoke:
  `signed-out -> sign in -> Use MemStack :8000 -> Login -> Chats -> Send workspace message`
- Browser plugin smoke:
  `signed-out -> five workflow chips fit -> sign in -> Use MemStack :8000 -> Login -> Chats -> Background chip -> Send workspace task`
- Browser plugin evidence after sending a task shows the latest right-panel
  events include `user_message`, `message`, and `ack` with `action:
  "send_message"` plus a real `conversation_id`.
- Browser plugin signed-in command-palette script timed out in this environment
  after login, resetting the Browser session. The same signed-in command
  palette flow was then verified with independent Playwright.
- Independent Playwright desktop smoke confirms the signed-out page loads with
  five visible workflow chips, no visible password literal, and no console
  warnings/errors.
- Independent Playwright mobile smoke at `390x844` confirms the signed-out
  composer has no horizontal overflow and the mobile sidebar is hidden.
- Console health after favicon fix: no browser warnings/errors on signed-out load.
- `cargo test`
- `make desktop`
- `make desktop-bundle`
- Computer Use capture of GitHub Copilot.app reference UI.
- Computer Use capture of the rebuilt release
  `agi-stack Desktop.app` signed-out UI.
- Computer Use capture of the final release `.app` after the command-palette
  accessibility fix confirms the signed-out shell still renders through the
  native bundle. Browser/Playwright verify the command-palette accessible names.
- Computer Use capture of the rebuilt release `.app` after the workspace-tab and
  new-session fixes confirms the signed-out native shell renders with workflow
  chips, connection warning, composer controls, and a working Command palette
  dialog focused on `Search commands`.
- Computer Use capture of the rebuilt release `.app` after the login-flow fix
  confirms the native sign-in dialog opens with `Login` enabled, successful
  login lands directly in Chat, and sending a native release message creates an
  `Agent task Accepted` card in the conversation timeline.
- Computer Use capture of the rebuilt release `.app` after the signed-in
  session-tree fix confirms login lands in Chat, Sessions renders as `Chats` +
  project root + `New session in 默认项目` + child sessions, a workspace message
  creates an `Agent task Accepted` card, and a newly created session also lands
  in Chat before accepting its first task message.
- Computer Use capture of the rebuilt release `.app` after the grouping-label
  fix confirms a clean release launch produces one native window, login reaches
  Chat, switching Session grouping to `Recent first` changes the root to
  `Recent sessions 50 sessions in 默认项目`, and the recent list remains usable.
- Computer Use capture of GitHub Copilot.app confirms the signed-in reference
  sidebar has Quick links, Sessions, and bottom user/settings controls without a
  separate tools group. Computer Use capture of the rebuilt release `.app`
  confirms the signed-in desktop sidebar now matches that structure, and a
  workspace message still creates an `Agent task Accepted` card.
- Computer Use capture of the rebuilt release `.app` after the `New chat` and
  composer-submit fixes confirms login reaches Chat, signed-in Sessions includes
  `Chats` -> `New chat` -> project root -> `New session in 默认项目`, `New chat`
  creates a fresh workspace and lands in Chat, and keyboard entry followed by
  `Enter` creates a user message plus an `Agent task Accepted` card.
- Computer Use follow-up reproduced that the send button path submits a second
  workspace message, but a later Agent socket `error` event flipped both cards
  in the same conversation to `Needs attention`. The follow-up fix scopes
  socket status updates to the exact `message_id` or the latest same-conversation
  card. Rebuilt release verification was limited by Computer Use returning
  `cgWindowNotFound` after the app restart, while the release process remained
  alive.
- Browser fallback validation after Computer Use returned `cgWindowNotFound`
  and Browser DOM snapshot returned `incrementalAriaSnapshot is not a function`:
  local `http://127.0.0.1:5173/` renders signed-out with the up-arrow send
  glyph and no console warnings/errors; login against `127.0.0.1:8000` reaches
  Chat, `New chat` creates a fresh workspace, clicking the green up-arrow send
  button creates a user message plus an `Agent task Accepted` card, and the
  signed-in screenshot shows the Copilot-like up-arrow composer affordance.
- Computer Use comparison of GitHub Copilot.app and the release desktop client
  found the signed-in Chat composer still exposed `Connected` as visible footer
  text where Copilot uses a compact status/control cluster; this follow-up
  removes the text from the visual layout without changing send behavior.
- Rebuilt release `.app` verification confirms login reaches Chat, the composer
  visually shows only the compact status dot next to the green up-arrow send
  button, and sending `compact status dot regression 1783579` creates a user
  message plus an `Agent task Accepted` card.
- Computer Use comparison found the signed-in Chat model selector still showed
  `Local model` while both the signed-out composer and GitHub Copilot reference
  show a concrete model name; this follow-up keeps the authenticated composer on
  `Claude Fable 5 · 1M`.
- Rebuilt release `.app` verification confirms login reaches Chat, the signed-in
  model selector now announces `Model selector, Claude Fable 5 · 1M`, and
  sending `model label regression 1783580` creates a user message plus an
  `Agent task Accepted` card.
- Computer Use comparison of GitHub Copilot.app confirms the authenticated
  message input placeholder says `Describe a task to run autonomously. Type /
  for commands, @ for files, or # for issues...`; this follow-up applies the
  same task-oriented empty-state copy to the signed-in Chat composer.
- Rebuilt release `.app` verification confirms login reaches Chat, the signed-in
  empty input announces the task-oriented Copilot placeholder, and sending
  `placeholder regression 1783581` creates a user message plus an
  `Agent task Accepted` card.
- Computer Use New chat edge pass confirms the signed-in sidebar creates a fresh
  workspace, the Chat composer stays enabled, and sending
  `empty chat state regression 1783582` creates a user message plus an
  `Agent task Accepted` card; this follow-up removes the visible
  `No messages loaded for this workspace.` engineering empty-state from new
  Chat sessions so the conversation area matches Copilot's quieter blank start.
- Computer Use post-fix release verification confirms the new Chat conversation
  area now starts visually blank with only the composer visible; comparison with
  GitHub Copilot.app found the next composer parity gap in control names, so
  this follow-up aligns the Chat footer labels to `Mode: Autopilot, Command +
  Shift + M`, `Select model`, `Reasoning effort: Medium`, and
  `AI credits quota: 100% used`.
- Computer Use comparison of the Copilot `+` menu shows `Add files...` and
  `Add folder...` under `Add files or folders`; this follow-up applies the same
  two-item context menu to the desktop composer and removes the extra
  `Reference workspace` item.
- Computer Use comparison of the Copilot `AI credits quota: 100% used` control
  shows it opens Accounts / Usage & Plan; this follow-up changes the Chat
  composer quota status from a static dot into a pop-up button that opens a
  matching Usage & Plan settings section.
- Computer Use comparison of the Copilot Workspace Plan tab shows a structured
  vertical plan list with status nodes rather than raw debug JSON; this
  follow-up changes loaded plan snapshots to render as a compact status tree,
  with raw JSON collapsed behind `Raw snapshot`.
- Computer Use comparison of the Copilot model picker shows `Select model` as a
  combobox rather than a generic pop-up button; this follow-up changes the
  desktop composer model control to an editable combobox backed by listbox
  options while preserving the compact footer layout.
- `pnpm build`
- `cargo test` in `apps/desktop/src-tauri`
- `make desktop-bundle`
- `make desktop-bundle-smoke`
- Local login/workspace/conversation/WS smoke against `127.0.0.1:8000`
- `git diff --check -- agi-stack/apps/desktop`
- `mcp__gitnexus.detect_changes({scope: "staged"})` reports low risk with no
  changed symbols or affected execution processes for the staged desktop files.
- Browser plugin DOM snapshot failed in this pass with
  `incrementalAriaSnapshot is not a function`, so rendered validation fell back
  to `agent-browser` against `http://127.0.0.1:5173/`.
  agent-browser Board toolbar QA verifies the signed-in
  `Desktop workspace 2026-07-09 21:39:01` workspace exposes Memory scope,
  Agent layout, Zoom, View, and Filter controls. Changing scope/view/filter/
  layout/zoom updates the state to `0 visibleCompactgridproject`, applies
  `lane-grid board-view-compact layout-grid`, and sets `--board-zoom: 1.1`.
  List mode keeps the `blocked` filter and shows
  `No tasks match the current board filter.` Console output only contains
  Vite/React dev info and `agent-browser errors --json` reports no page errors.
  Mobile smoke at `390x844` verifies no horizontal overflow, no Vite overlay,
  and the toolbar starts directly below the Board header. Screenshots:
  `/tmp/agi-desktop-board-toolbar-flow.png`,
  `/tmp/agi-desktop-board-toolbar-list.png`, and
  `/tmp/agi-desktop-board-toolbar-mobile.png`.
- Browser plugin page identity succeeds for `http://127.0.0.1:5173/`, but DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`, so the
  topbar run-control QA used `agent-browser`. agent-browser verifies the
  signed-in `Desktop workspace 2026-07-09 21:39:01` workspace renders the run
  state chip plus Pause/Resume, Stop, Runtime target, and Live/Offline controls.
  Pause changes the chip to `Run state Paused` and swaps the action to Resume;
  Resume returns `Run state Running`; Runtime changes to `staging`;
  Offline/Live update `aria-pressed`; Stop changes the chip to
  `Run state Stopped`, switches updates offline, and exposes Resume. At
  `1280x720`, the less critical open-in-apps group hides to preserve title and
  run-control space with zero horizontal overflow. Mobile smoke at `390x844`
  hides the expanded controls, keeps the compact Run/status buttons reachable,
  reports zero horizontal overflow, and has no Vite overlay or page errors.
  Console output only contains Vite/React dev info and HMR notices. Screenshots:
  `/tmp/agi-desktop-run-controls.png` and
  `/tmp/agi-desktop-run-controls-mobile.png`.
- Browser plugin page identity again succeeds for `http://127.0.0.1:5173/`,
  with no Browser console warnings/errors, but DOM snapshot still fails with
  `incrementalAriaSnapshot is not a function`; rendered navigation QA used
  `agent-browser`. agent-browser verifies signed-out and signed-in Quick links
  show `Runs`, `Agents`, `Memory`, `Artifacts`, and `Runtime`. In the signed-in
  `Desktop workspace 2026-07-09 21:39:01` workspace, clicking Runs selects the
  Board pane, Agents selects Workspace Background agents, Memory selects the
  Status Memory tab, Artifacts selects Workspace Artifacts with 39 rows, and
  Runtime selects Settings. Mobile smoke at `390x844` verifies the section menu
  contains `Runs`, `Agents`, `Memory`, `Artifacts`, `Runtime`, plus tool entries,
  keeps Artifacts selected, and has zero horizontal overflow, no Vite overlay,
  and no page errors. Screenshots: `/tmp/agi-desktop-web-nav.png` and
  `/tmp/agi-desktop-web-nav-mobile.png`.
- Browser plugin page identity succeeds for the Runs list pass, and Browser
  console has no warnings/errors, but Browser DOM snapshot still fails with
  `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies signed-out Quick links still render,
  manual/API-key runtime mode shows the new sidebar `Runs` region with a current
  session row, Pause updates both the titlebar and run row to `Paused`, clicking
  the run row opens the Board pane, and Stop updates both surfaces to `Stopped`.
  Desktop and mobile checks report zero horizontal overflow, no Vite overlay,
  and no page errors. The local `local-project` backend returned no visible
  workspaces/conversations in this pass, so the exercised rendered path is the
  current-session fallback row rather than a multi-row data-backed list.
  Screenshots: `/tmp/agi-desktop-runs-sidebar.png`,
  `/tmp/agi-desktop-runs-sidebar-mobile.png`, and
  `/tmp/agi-desktop-runs-sidebar-mobile-menu.png`.
- Browser plugin page identity succeeds for the `Create new run` pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies manual/runtime mode exposes the
  icon-only `Create new run` button, clicking it creates `Run #1`, selects the
  row, and opens the Board. A second click creates `Run #2`, keeps it first and
  selected, and leaves the current-session fallback below the local draft rows.
  Desktop and mobile checks report zero horizontal overflow, no Vite overlay,
  and no page errors. Console output only contains Vite/React dev info and HMR
  notices. Screenshots: `/tmp/agi-desktop-create-run.png` and
  `/tmp/agi-desktop-create-run-mobile.png`.
- Browser plugin page identity succeeds for the run-titlebar pass, and Browser
  console has no warnings/errors, but Browser DOM snapshot still fails with
  `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies manual/runtime mode can create two
  local runs, keeps `Run #2` first and selected, opens the Board, and updates
  the titlebar to `Run: Run #2`. Desktop and mobile checks report zero
  horizontal overflow, no Vite overlay, and no page errors. Console output only
  contains Vite/React dev info. Screenshots:
  `/tmp/agi-desktop-run-titlebar.png` and
  `/tmp/agi-desktop-run-titlebar-mobile.png`.
- Browser plugin page identity succeeds for the composer runtime-target pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies manual/runtime mode can open the Chat
  composer, use the bottom composer `Runtime target` control to select
  `Remote staging`, and see the titlebar runtime select synchronize to
  `staging` / `Remote staging`. Desktop and `390x844` mobile checks report zero
  horizontal overflow, no Vite overlay, and no page errors. The mobile compact
  label was widened so `Staging` displays without truncation. Console output
  only contains Vite/React dev info and the CSS HMR notice. Screenshots:
  `/tmp/agi-desktop-composer-runtime-target.png` and
  `/tmp/agi-desktop-composer-runtime-target-mobile.png`.
- Browser plugin page identity succeeds for the slash-command pass, and Browser
  console has no warnings/errors, but Browser DOM snapshot still fails with
  `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies manual/runtime mode can open the Chat
  composer, show the new `Slash commands` button, click it, open the Command
  palette, and focus the `Search commands` input. Desktop and `390x844` mobile
  checks report zero horizontal overflow, no Vite overlay, and no page errors;
  the mobile slash button remains a stable 32px control. Console output only
  contains Vite/React dev info. Screenshots:
  `/tmp/agi-desktop-slash-command.png` and
  `/tmp/agi-desktop-slash-command-mobile.png`.
- Browser plugin page identity succeeds for the run-actions menu pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. agent-browser verifies manual/runtime mode shows the new
  topbar `More run actions` button, opens the menu, preserves disabled states
  for Pause/Stop/Run/Refresh when no project/workspace is configured, and uses
  `Open chat` to close the menu and return to the Chat composer. Desktop and
  `390x844` mobile checks report zero horizontal overflow, no Vite overlay, and
  no page errors. The mobile menu stays within the 390px viewport. Console
  output only contains Vite/React dev info. Screenshots:
  `/tmp/agi-desktop-run-actions-menu.png` and
  `/tmp/agi-desktop-run-actions-menu-mobile.png`.
- Browser plugin page identity succeeds for the sidebar runtime-monitor pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks plus `agent-browser`. Manual/runtime mode now
  shows a `Runtime monitor` region under Runs with `Local Rust Core`, connection
  `idle`, live state `waiting`, scope `setup`, events `0`, and queue `0`.
  Clicking `Open Runtime Monitor` from the Board returns to Runtime settings
  with the Runtime quick link selected. Desktop and `390x844` mobile checks
  report zero horizontal overflow, no Vite overlay, and no page errors; on
  mobile the sidebar remains hidden while the compact section switcher stays
  visible. Console output only contains Vite/React dev info. Screenshots:
  `/tmp/agi-desktop-runtime-monitor.png` and
  `/tmp/agi-desktop-runtime-monitor-mobile.png`.
- Browser plugin page identity succeeds for the titlebar run-clock pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks plus `agent-browser`. Manual/runtime mode can
  open Runs/Board and shows the new clock chip after the `Running` state chip
  with aria label `Run time never`, backed by the current selected-run time
  fallback. Desktop checks report zero horizontal overflow, no Vite overlay,
  no page errors, and clean console output. Mobile `390x844` checks verify the
  clock and run-state chips hide with the compact titlebar rules while the
  section switcher remains visible and overflow stays at zero. Screenshots:
  `/tmp/agi-desktop-run-clock.png` and
  `/tmp/agi-desktop-run-clock-mobile.png`.
- Browser plugin page identity succeeds for the Board time-scale pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks plus `agent-browser`. Manual/runtime mode can
  open Runs/Board, Flow mode shows the `00:00 00:05 00:10 00:15 Now 00:25 00:30`
  run graph scale with a visible Now line between the board state chips and
  scrollable lane grid, and List mode removes the time scale while keeping the
  task table. Desktop and `390x844` mobile checks report zero page-level
  horizontal overflow, no Vite overlay, no page errors, and clean console
  output. Screenshots: `/tmp/agi-desktop-board-time-scale-flow.png`,
  `/tmp/agi-desktop-board-time-scale-list.png`, and
  `/tmp/agi-desktop-board-time-scale-mobile.png`.
- Browser plugin page identity succeeds for the Board lane now-line pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks plus `agent-browser`. Manual/runtime mode can
  open Runs/Board, Flow mode now continues the current-time marker through the
  lane grid, the lane marker aligns with the time-scale marker, and it uses
  `pointer-events: none` so task-card interactions are not intercepted. List
  mode removes the lane marker with the Flow-only grid. Desktop and `390x844`
  mobile checks report zero page-level horizontal overflow, no Vite overlay,
  no page errors, and clean console output. Screenshots:
  `/tmp/agi-desktop-board-now-line-flow.png`,
  `/tmp/agi-desktop-board-now-line-list.png`, and
  `/tmp/agi-desktop-board-now-line-mobile.png`.
- Browser plugin page identity succeeds for the Board swimlane pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks plus `agent-browser`. Manual/runtime mode can open
  Runs/Board, set the Board `View` selector to `Swimlane`, and the Flow board
  switches from column lanes to horizontal rows with a 148px lane label column,
  status-dot sublabels, and track-grid backgrounds. Desktop checks verify 5
  Swimlane rows, aligned time-scale/lane now markers, no Vite overlay, no page
  errors, and zero page-level horizontal overflow. Mobile `390x844` initially
  exposed marker drift from a fixed 640px lane-grid minimum; after removing
  that minimum, both markers align at `x=284` and page overflow remains zero.
  Screenshots: `/tmp/agi-desktop-board-swimlane.png` and
  `/tmp/agi-desktop-board-swimlane-mobile.png`.
- Browser plugin page identity succeeds for the Background agents event-count
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser read-only DOM evaluation plus `agent-browser`. Manual/runtime mode can
  open Workspace > Background agents from the overflow tab menu, event filters
  now expose per-kind counts in their labels (`All`, `Tools`, `Reasoning`,
  `Messages`, `System`, `Errors`), and selecting `Tools events, 0 available`
  makes only that filter selected while enabling Clear. With no socket events
  loaded, the event-mix summary stays hidden and the existing `No background
  agents` empty state remains intact. Desktop checks show no Vite overlay, no
  page errors, and clean console output aside from dev-server info logs. Mobile
  `390x844` checks confirm the Review panel remains hidden at the narrow
  breakpoint and the settings pane has no error overlay. Screenshots:
  `/tmp/agi-desktop-event-summary-browser.png`,
  `/tmp/agi-desktop-event-summary-agent-browser.png`,
  `/tmp/agi-desktop-event-summary-mobile-browser.png`, and
  `/tmp/agi-desktop-event-summary-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Decision scope/Snooze pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  read-only DOM evaluation plus `agent-browser`. Manual/runtime mode can open
  Workspace > Changes, where the Human decision action area now includes an
  `Apply to this run only` checkbox and a `Snooze` button matching the prototype
  decision drawer. Approve and Request changes remain disabled without a loaded
  review packet, while the local scope checkbox and Snooze remain usable. QA
  clicks Snooze with the default run scope, clears the checkbox, clicks Snooze
  again, and verifies decision history records both `this run` and `workspace
  packet` details while the main status stays Pending. Desktop checks show no
  Vite overlay, no page errors, and clean console output aside from dev-server
  info logs. Mobile `390x844` checks confirm the Review panel remains hidden at
  the narrow breakpoint and the settings pane has no error overlay. Screenshots:
  `/tmp/agi-desktop-decision-scope-browser.png`,
  `/tmp/agi-desktop-decision-scope-agent-browser.png`,
  `/tmp/agi-desktop-decision-scope-mobile-browser.png`, and
  `/tmp/agi-desktop-decision-scope-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Decision full-diff entry pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser read-only DOM evaluation plus `agent-browser`. Manual/runtime mode can
  open Workspace > Changes, where the Human decision Files section now includes
  a `View full diff` action matching the prototype drawer. Clicking the action
  switches the Workspace review panel to the Artifacts tab and shows the
  existing artifact filters and empty state when no diff packet is loaded.
  Desktop checks show no Vite overlay, no page errors, and clean console output
  aside from dev-server info logs. Mobile `390x844` checks confirm the narrow
  shell remains stable and the Review panel stays hidden at that breakpoint.
  Screenshots: `/tmp/agi-desktop-decision-diff-browser.png`,
  `/tmp/agi-desktop-decision-diff-browser-artifacts.png`,
  `/tmp/agi-desktop-decision-diff-agent-browser.png`,
  `/tmp/agi-desktop-decision-diff-agent-browser-artifacts.png`, and
  `/tmp/agi-desktop-decision-diff-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Decision run-state pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  read-only DOM evaluation plus `agent-browser`. In the signed-in
  `Desktop workspace 2026-07-09 21:39:01` workspace with 80 events and 39
  artifacts, Workspace > Changes shows `Updates review and selected run`.
  Clicking `Request changes` changes the titlebar and Runs row to `Paused`,
  exposes `Resume selected run`, and records `run paused`; clicking `Approve`
  changes the selected run back to `Running`, exposes `Pause selected run`, and
  records `run continues`. Desktop checks show no Vite overlay, no page errors,
  and clean Browser console output aside from dev-server info logs. Mobile
  `390x844` checks confirm `documentWidth` and `bodyWidth` stay at 390; the
  wider Background/Artifacts tab buttons are clipped inside the intended
  horizontal tab scroller rather than creating page-level overflow. Screenshots:
  `/tmp/agi-desktop-decision-run-state-before-browser.png`,
  `/tmp/agi-desktop-decision-run-state-request-browser.png`,
  `/tmp/agi-desktop-decision-run-state-approve-browser.png`,
  `/tmp/agi-desktop-decision-run-state-mobile-browser.png`,
  `/tmp/agi-desktop-decision-run-state-agent-before.png`,
  `/tmp/agi-desktop-decision-run-state-agent-request.png`,
  `/tmp/agi-desktop-decision-run-state-agent-approve.png`, and
  `/tmp/agi-desktop-decision-run-state-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Board timeline task-pill pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. A local QA workspace
  `Desktop board timeline QA 1783615297497` was created through the local API
  with 4 real workspace tasks carrying timeline placement metadata. In Runs >
  Board, Timeline mode renders 5 lanes, the `00:00 ... Now ... 00:30` time
  scale, and 4 `.task-timeline-pill` controls while ordinary `.task-card`
  controls are absent in Flow mode. Swimlane mode keeps the same 4 task pills,
  applies `lane-grid board-view-swimlane layout-lanes`, and aligns the
  time-scale and lane now-lines at `x=633`. Desktop and `390x844` mobile checks
  report `documentWidth` / `bodyWidth` equal to the viewport, no Vite overlay,
  no page errors, and clean console output aside from dev-server info logs. The
  mobile overflow candidates are contained inside the intended Board timeline
  scroller. Screenshots:
  `/tmp/agi-desktop-board-timeline-agent-browser.png`,
  `/tmp/agi-desktop-board-timeline-swimlane-agent-browser.png`, and
  `/tmp/agi-desktop-board-timeline-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Board task selection review
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  `agent-browser`. In the same local QA workspace
  `Desktop board timeline QA 1783615297497`, Runs > Board initially selects
  `Publish verification report` and shows `QA seed for Publish verification
  report` in the Human decision panel. Clicking the `Apply runner patch`
  timeline pill changes the selected pill to `Apply runner patchin_progress`,
  updates the Human decision heading to `Apply runner patch`, and changes the
  summary to `QA seed for Apply runner patch`. Desktop checks report no Vite
  overlay, no page errors, clean console output aside from dev-server info logs,
  and `documentWidth` / `bodyWidth` equal to the viewport. Mobile `390x844`
  keeps the Board visible with 4 task pills, preserves the selected
  `Apply runner patch` review context, and has no page-level horizontal
  overflow. Screenshots:
  `/tmp/agi-desktop-board-selection-review-agent-browser.png` and
  `/tmp/agi-desktop-board-selection-review-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Workspace panel close pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator actions plus `agent-browser`. After local login, the Workspace review
  header exposes exactly one `Close workspace panel` button. Clicking it removes
  `.review-panel`, applies `.workbench-layout.review-panel-collapsed`, and
  exposes exactly one topbar `Show workspace panel` restore control; clicking
  that restore control brings the review panel and close button back. Desktop
  and mobile `390x844` checks report no Vite overlay, no page errors, clean
  console output aside from dev-server info logs, and `documentWidth` /
  `bodyWidth` equal to the viewport. Mobile also verifies the in-panel close
  action collapses the panel without page-level horizontal overflow.
  Screenshots:
  `/tmp/agi-desktop-review-panel-close-agent-browser.png`,
  `/tmp/agi-desktop-review-panel-reopen-agent-browser.png`,
  `/tmp/agi-desktop-review-panel-close-mobile-agent-browser.png`, and
  `/tmp/agi-desktop-review-panel-close-mobile-collapsed-agent-browser.png`.
- Browser plugin page identity succeeds for the Create new run event pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator actions plus `agent-browser`. After local login, Runtime Monitor
  starts with `Events80` when the selected workspace has live socket history.
  Clicking `Create new run` selects `Run #1`, opens the Board, changes Runtime
  Monitor to `Events81`, and makes the Human decision packet show
  `Review background activity` with `New run #1 queued with local runtime.`.
  Switching to Agents / Background agents shows `81 of 81` events and the
  queued message event at the top after nested socket timestamps are respected.
  A clean session with no loaded socket events verifies the stricter case:
  Runtime Monitor changes from `Events0` to `Events1`, Background agents shows
  `1 of 1`, `Messages events, 1 available`, and the only event row is
  `Messages / message / System / received / New run #1 queued with local runtime.`.
  Desktop checks show
  no Vite overlay, no page errors, clean console output aside from dev-server
  info logs, and `documentWidth` / `bodyWidth` equal to the viewport. Mobile
  `390x844` confirms no page-level horizontal overflow after the run event is
  created. Screenshots:
  `/tmp/agi-desktop-create-run-event-agent-browser.png`,
  `/tmp/agi-desktop-create-run-background-event-agent-browser.png`, and
  `/tmp/agi-desktop-create-run-event-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Create new run Planning pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks plus `agent-browser`. After local login,
  clicking `Create new run` creates `Run #1` in `Planning`, selects the row,
  opens the Board, exposes `Pause selected run`, and shows
  `New run #1 queued with local runtime.`. Clicking Pause changes the titlebar
  and Runs row to `Paused` with `Resume selected run`; clicking Resume changes
  them to `Running` with `Pause selected run`. Desktop and `390x844` mobile
  checks report no page-level horizontal overflow, no Vite overlay, no page
  errors, and clean console output aside from Vite/React dev info. Screenshots:
  `/tmp/agi-desktop-create-run-planning-agent-browser.png`,
  `/tmp/agi-desktop-create-run-paused-agent-browser.png`, and
  `/tmp/agi-desktop-create-run-planning-mobile-agent-browser.png`.
- Browser plugin page identity succeeds for the Board command-bar pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. After local login and Runtime refresh, Runs > Board
  shows the new run command bar with placeholder
  `Steer this run or start a new task...`, model `OpenAI gpt-4o-mini`, runtime
  `Local Rust Core`, and a disabled send button until text is entered. Clicking
  Slash commands opens the Command palette and focuses `Search commands`.
  Changing the Board runtime select to `Remote staging` updates the titlebar
  runtime to `staging`; changing it back restores `local`. Submitting
  `board command parity 1783618428520` clears the Board input, increments the
  Runtime Monitor queue from 0 to 1, and the Chat transcript shows an
  `Agent task` card containing the same command. The local Agent launch then
  surfaced the pre-existing `Cannot reach http://127.0.0.1:8000` error in the
  task card rather than silently succeeding, while the workspace message save
  path completed. Desktop and `390x844` mobile checks report no page-level
  horizontal overflow, no Vite overlay, and clean Browser console output.
  Screenshots: `/tmp/agi-desktop-board-command-bar-browser.png`,
  `/tmp/agi-desktop-board-command-submit-browser.png`,
  `/tmp/agi-desktop-board-command-chat-browser.png`, and
  `/tmp/agi-desktop-board-command-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board run-scope memory pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. After local login, Runs > Board shows the selected
  data-backed run in the Memory scope first option, for example
  `Desktop workspace 2026-07-09 16:11:06: desktop stream QA second 1783588579777
  (isolated)`, and the Board state line echoes the same scope. Clicking
  `Create new run` selects `Run #1`, changes the titlebar run state to
  `Planning`, leaves the local queue event visible, and updates the Memory
  scope option plus state line to `Run #1 (isolated)`. Desktop and `390x844`
  mobile checks report no page-level horizontal overflow, no Vite overlay, and
  clean Browser console output. Screenshots:
  `/tmp/agi-desktop-board-run-scope-browser.png` and
  `/tmp/agi-desktop-board-run-scope-mobile-browser.png`.
- Browser plugin page identity succeeds for the topbar Resume control pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. After local login, the signed-in topbar shows
  `Pause`, the new independent `Resume`, `Stop`, and `Run`, matching the web
  prototype control set. In the initial Running state, direct Resume is visible
  and disabled. Creating a local run moves the selected run to Planning, enables
  direct Resume, and preserves the queued local runtime event; clicking direct
  Resume changes the titlebar and Runs row to Running and disables direct
  Resume again. Pausing the same run changes it to Paused and re-enables direct
  Resume; clicking direct Resume again returns the run to Running. Desktop and
  `390x844` mobile checks report no page-level horizontal overflow, no Vite
  overlay, and clean Browser console output. Screenshots:
  `/tmp/agi-desktop-run-resume-planning-browser.png`,
  `/tmp/agi-desktop-run-resume-running-browser.png`, and
  `/tmp/agi-desktop-run-resume-mobile-browser.png`.
- Browser plugin page identity succeeds for the topbar Run control parity pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. After manual runtime setup with a development
  workspace scope, clicking `Create new run` opens Board with `Run #1` in
  `Planning`. Clicking the topbar `Run` control changes the titlebar and Runs
  row to `Running`, restores live updates, and keeps the user on the Board
  instead of routing to Chat. After the runtime refresh settles, the page still
  contains `.board-shell`, not `.chat-shell`, and `Run selected session` is
  enabled again. Mobile `390x844` checks verify the compact Run button remains
  reachable, Board stays visible, and `documentWidth` / `bodyWidth` remain 390.
  Screenshots: `/tmp/agi-desktop-run-button-board-parity.png` and
  `/tmp/agi-desktop-run-button-board-parity-mobile.png`.
- Browser plugin page identity succeeds for the Runs row-state pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. After local login, clicking `Create new run` creates
  `Run #1`, `Stop` changes it to `Stopped`, and clicking `Create new run`
  again selects `Run #2` in `Planning` while the non-selected `Run #1` remains
  `Stopped` with `run-state-stopped`. Data-backed `active` rows display
  `Running` with `run-state-running`. Desktop and `390x844` mobile checks
  report no page-level horizontal overflow, no Vite overlay, and clean Browser
  console output. Screenshots:
  `/tmp/agi-desktop-run-row-state-browser.png` and
  `/tmp/agi-desktop-run-row-state-mobile-browser.png`.
- Browser plugin page identity succeeds for the Runtime monitor health pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. After local login with the MemStack :8000
  preset, the Runtime monitor first shows `Starting`, then settles to
  `Healthy` with aria label `Runtime health Healthy` while preserving real
  Live/Scope/Events/Queue values. Desktop checks report no Vite overlay and
  clean Browser console output; `390x844` mobile checks report no page-level
  horizontal overflow or overlay while the monitor remains hidden by the
  existing narrow-screen layout. Screenshots:
  `/tmp/agi-desktop-runtime-health-browser.png` and
  `/tmp/agi-desktop-runtime-health-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board selection event pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. After local login with the MemStack :8000
  preset, Runs > Board shows the seeded timeline tasks. Clicking
  `Apply runner patch` selects that task, opens the matching Workspace Changes
  packet, and increments Background agents from 80 to 81 with a new selected
  `System / selection` row whose detail is
  `Apply runner patch selected in Timeline.`. Desktop checks report no Vite
  overlay and clean Browser console output; `390x844` mobile checks report no
  page-level horizontal overflow or overlay while the hidden review panel keeps
  the selected event state. Screenshots:
  `/tmp/agi-desktop-board-selection-event-browser.png` and
  `/tmp/agi-desktop-board-selection-event-mobile-browser.png`.
- Browser plugin page identity succeeds for the Background Clear pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. MemStack :8000 was not reachable in this pass, so
  QA used the manual local-runtime path: `Create new run` adds one local queued
  event, Background agents shows `1 of 1`, and `Clear` is enabled. Clicking
  `Clear` removes the local queued event, changes Background agents to `idle`,
  disables `Clear`, and leaves no event rows. Desktop checks report no Vite
  overlay and clean Browser console output; `390x844` mobile checks report no
  page-level horizontal overflow or overlay while the hidden review panel keeps
  the cleared state. Screenshots:
  `/tmp/agi-desktop-background-clear-browser.png` and
  `/tmp/agi-desktop-background-clear-mobile-browser.png`.
- Browser plugin page identity succeeds for the Human decision event pass, and
  Browser console has no warnings/errors, but Browser DOM snapshot still fails
  with `incrementalAriaSnapshot is not a function`; rendered QA used Browser
  locator/evaluate checks. QA used the manual local-runtime path:
  `Create new run` -> `Request changes`. The run state changes to `Paused`,
  Background agents shows `2 of 2`, and the newest row is
  `Messages / decision` from `Human decision` with status `changes` and detail
  `Requested changes. Executor is waiting for revision.`. Desktop checks report
  no Vite overlay; `390x844` mobile checks report no page-level horizontal
  overflow or overlay while the hidden review panel keeps the decision event
  state. Screenshots: `/tmp/agi-desktop-decision-event-browser.png` and
  `/tmp/agi-desktop-decision-event-mobile-browser.png`.
- Browser plugin page identity succeeds for the custom event Messages filter
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used the manual local-runtime path:
  `Create new run` -> `Request changes` -> Agents / Background agents ->
  `Messages` filter. Background agents reports `All2`, `Messages2`, and
  `System0`; selecting `Messages` leaves both local interaction rows:
  `Messages / decision` from `Human decision` with status `changes` and
  `Messages / message` from `System` with detail
  `New run #1 queued with local runtime.`. `390x844` mobile checks report no
  page-level horizontal overflow or overlay while preserving the Messages filter
  and both rows. Screenshots:
  `/tmp/agi-desktop-message-kind-agents-browser.png`,
  `/tmp/agi-desktop-message-kind-agents-ultrawide-browser.png`, and
  `/tmp/agi-desktop-message-kind-mobile-browser.png`.
- Browser plugin page identity succeeds for the Create new run queue-message
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used the manual local-runtime path:
  `Create new run` -> `Request changes` -> Background agents -> `Messages`
  filter. Background agents reports `All2`, `Messages2`, and `System0`;
  selecting `Messages` keeps both `Messages / decision` and
  `Messages / message` rows visible. Desktop checks report no Vite overlay;
  `390x844` mobile checks report no page-level horizontal overflow or overlay
  while preserving `Messages2` and `System0`. Screenshots:
  `/tmp/agi-desktop-queue-message-browser-viewport.png` and
  `/tmp/agi-desktop-queue-message-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board Operator command event
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used a real MemStack `:8000` development
  workspace gate, then `Create new run` -> Board `Run command` ->
  Background agents -> `Messages` filter. Background agents reports `All83`,
  `Tools79`, `Messages4`, and `System0`, while omitting `Errors` because no
  error events are present; selecting `Messages` keeps
  the socket `workspace_message_created` row plus the local
  `Messages / message` row from `Operator` with status `received` and detail
  `operator command parity 1783622887657`. At `390x844`, the mobile Workspace
  section preserves the submitted command in the `Open chat` summary, while
  read-only DOM checks still contain the hidden Background `Messages4` filter
  and the same Operator row. Screenshots:
  `/tmp/agi-desktop-operator-command-browser.png` and
  `/tmp/agi-desktop-operator-command-mobile-agents-browser.png`.
- Browser plugin page identity succeeds for the Board timeline settings pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used a real MemStack `:8000` development
  workspace gate, then Runs > Board > `Task board settings`. The settings panel
  opens with `Now marker`, `Lane counts`, and `Progress bars`; after switching
  Board view to `Compact`, disabling those toggles removes both now-line DOM
  markers, lane count badges, and task progress bars while the Board status line
  changes to `now hidden` and `progress hidden`. Desktop and `390x844` mobile
  checks report no page-level horizontal overflow or framework overlay.
  Screenshots: `/tmp/agi-desktop-board-settings-browser.png` and
  `/tmp/agi-desktop-board-settings-mobile-browser.png`.
- Browser plugin page identity succeeds for the signed-out session tree pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Signed-out `Chats` now changes the selected
  session-tree row from `New session` to `Chats` with `aria-current="page"`;
  signed-out `Connect project` enters manual API connection settings with
  `Server URL`, `API key`, and `Connect runtime` controls visible. At `390x844`,
  the compact titlebar `API key` path opens the same settings surface with no
  page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-signedout-chats-browser.png`,
  `/tmp/agi-desktop-signedout-connect-project-browser.png`, and
  `/tmp/agi-desktop-signedout-connect-project-mobile-browser.png`.
- Browser plugin page identity succeeds for the signed-out Quick links selected
  state pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. In signed-out desktop,
  clicking `Runs`, `Agents`, `Artifacts`, and `Runtime` now gives the matching
  Quick link a visible selected state plus `aria-current="page"` instead of
  leaving the primary navigation unmarked. The `Runtime` click also keeps the
  signed-out `Connect project` row selected because it opens the same connection
  settings surface. At `390x844`, the existing compact layout hides Quick links
  and continues to report no page-level horizontal overflow or framework
  overlay. Screenshots:
  `/tmp/agi-desktop-signedout-quicklinks-browser.png` and
  `/tmp/agi-desktop-signedout-quicklinks-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board zoom-control parity pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used the local manual-runtime path:
  `Use API key` -> `Create new run` -> Runs > Board. The Board zoom control now
  uses icon buttons for both directions, reports `100%` with both controls
  enabled, clamps to `70%` with `Zoom task board out` disabled, and clamps to
  `140%` with `Zoom task board in` disabled while the lane grid CSS variable
  reports `0.7` / `1.4`. At `390x844`, an already-open Board run preserves
  `140%`, keeps the plus icon rendered in the disabled zoom-in button, and
  reports no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-board-zoom-browser.png` and
  `/tmp/agi-desktop-board-zoom-mobile-browser.png`.
- Browser plugin page identity succeeds for the runtime-target label parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. The signed-out composer runtime menu now
  shows `Local Rust Core` and `Staging Runtime` with no `Remote staging` copy.
  QA then used the local manual-runtime path: `Use API key` -> `Create new run`
  -> Runs > Board. Board command-bar runtime options and the titlebar runtime
  select both show `Staging Runtime`; selecting it from the Board command bar
  synchronizes the titlebar value to `staging` and the runtime monitor heading
  to `Staging Runtime`. At `390x844`, the existing Board run preserves
  `Staging Runtime` in the command-bar select, has no `Remote staging` text, and
  reports no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-runtime-target-label-browser.png` and
  `/tmp/agi-desktop-runtime-target-label-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board accessible-label parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used the local manual-runtime path:
  `Use API key` -> `Create new run` -> Runs > Board. The Board settings control
  now exposes `Timeline settings`, opens the `Timeline settings` panel with
  `Now marker`, `Lane counts`, and `Progress bars`, and no longer exposes the
  old `Task board settings` accessible name. The Board command submit button now
  exposes `Send command`, matching the web prototype, and no longer exposes
  `Send run command`. At `390x844`, the already-open Board run preserves the
  `Timeline settings` panel and `Send command` label, reports no old labels, and
  has no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-board-labels-browser.png` and
  `/tmp/agi-desktop-board-labels-mobile-browser.png`.
- Browser plugin page identity succeeds for the Board settings-icon parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. QA used the local manual-runtime path:
  `Use API key` -> `Create new run` -> Runs > Board. The `Timeline settings`
  button now renders the Radix sliders/mixer SVG shape instead of the previous
  gear icon while preserving `aria-expanded`, opening the `Timeline settings`
  panel, and keeping `Now marker`, `Lane counts`, and `Progress bars` pressed.
  At `390x844`, the open Board run preserves the sliders/mixer settings icon,
  the settings panel, `Send command`, and zero old Board settings / send labels,
  with no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-board-settings-icon-browser.png` and
  `/tmp/agi-desktop-board-settings-icon-mobile.png`.
- Browser plugin page identity succeeds for the Board `Run graph` landmark
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype wraps its Board surface with `aria-label="Run graph"`, and the
  desktop Board shell now exposes the same label. QA used the local
  manual-runtime path: `Use API key` -> `Create new run` -> Runs > Board.
  Desktop checks find exactly one `section[aria-label="Run graph"]`, keep the
  visible `Board` heading, preserve the `Timeline settings` sliders icon and
  `Send command`, and report zero old Board settings / send labels. At
  `390x844`, the same `Run graph` landmark remains unique with no page-level
  horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-run-graph-label-browser.png` and
  `/tmp/agi-desktop-run-graph-label-mobile.png`.
- Browser plugin page identity succeeds for the Workspace close-drawer label
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype uses `aria-label="Close drawer"` for the Human decision drawer
  close control, and the desktop Workspace review panel close control now uses
  the same accessible label. QA used the manual-runtime path:
  `Use API key` -> Workspace review panel -> `Close drawer`. Desktop checks
  find exactly one `Close drawer` control and zero old `Close workspace panel`
  controls before the click; clicking it removes the review panel, applies
  `review-panel-collapsed`, and exposes `Show workspace panel`. At `390x844`,
  the collapsed state remains, the old label stays absent, and there is no
  page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-close-drawer-before.png`,
  `/tmp/agi-desktop-close-drawer-after.png`, and
  `/tmp/agi-desktop-close-drawer-mobile.png`.
- Browser plugin page identity succeeds for the Workspace Human decision label
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype labels the Human decision drawer as `aria-label="Human decision"`,
  and the desktop review decision surface now exposes the same accessible label
  instead of `Human decision review`. QA used the manual-runtime path:
  `Use API key` -> Workspace Changes. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]`, zero old
  `Human decision review` labels, the visible `Human decision` kicker, and the
  Approve / Request changes action area. At `390x844`, the same label remains
  unique, the old label stays absent, `Close drawer` remains available, and
  there is no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-label-browser.png` and
  `/tmp/agi-desktop-human-decision-label-mobile.png`.
- Browser plugin page identity succeeds for the Workspace Artifacts `Grid view`
  label parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype labels the Artifacts view toggle as `aria-label="Grid view"`,
  and the desktop Artifacts toggle now exposes the same fixed label while
  keeping `aria-pressed` as the list/grid state. QA used the manual-runtime path:
  `Use API key` -> `Artifacts section` -> Workspace Artifacts. Desktop checks
  find exactly one `Grid view` control, zero old `Switch artifacts to grid view`
  / `Switch artifacts to list view` labels, and `Artifact sort`; clicking
  `Grid view` changes `aria-pressed` from `false` to `true`. At `390x844`, the
  Artifacts tab remains selected in DOM checks, `Grid view` stays unique and
  pressed, the old labels remain absent, and there is no page-level horizontal
  overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-grid-view-label-before.png`,
  `/tmp/agi-desktop-grid-view-label-after.png`, and
  `/tmp/agi-desktop-grid-view-label-mobile.png`.
- Browser plugin page identity succeeds for the topbar Runtime label parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Source comparison found the web prototype
  labels the topbar runtime select as `aria-label="Runtime"`, and the desktop
  titlebar runtime select now exposes the same label while Board command-bar
  runtime selection keeps `Runtime target`. QA used the manual-runtime path:
  `Use API key` -> titlebar Runtime select. Desktop checks find exactly one
  `select[aria-label="Runtime"]`, zero titlebar `Runtime target` selects,
  options `Local Rust Core` and `Staging Runtime`, and selecting `Staging
  Runtime` changes the select value to `staging`. At `390x844`, compact layout
  hides the topbar select visually but keeps the DOM label as `Runtime`, with no
  old `Runtime target` select, no page-level horizontal overflow, and no
  framework overlay. Screenshots: `/tmp/agi-desktop-runtime-label-browser.png`
  and `/tmp/agi-desktop-runtime-label-mobile.png`.
- Browser plugin page identity succeeds for the Primary navigation landmark
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype labels the main sidebar nav as `aria-label="Primary"`, and the
  desktop quick-links nav now exposes the same label instead of
  `desktop sections`. Desktop checks find exactly one
  `nav[aria-label="Primary"]`, zero old `desktop sections` navs, and the
  expected Runs / Agents / Memory / Artifacts / Runtime controls inside it;
  clicking `Artifacts section` sets the Artifacts quick link selected. At
  `390x844`, compact layout hides the sidebar nav visually but keeps the DOM
  label as `Primary`, with no old label, no page-level horizontal overflow, and
  no framework overlay. Screenshots: `/tmp/agi-desktop-primary-nav-browser.png`
  and `/tmp/agi-desktop-primary-nav-mobile.png`.
- Browser plugin page identity succeeds for the Workspace Artifacts section
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype wraps Artifacts in `section[aria-label="Artifacts"]`, and the
  desktop workspace Artifacts panel now exposes the same region label. QA used
  the manual-runtime path: `Use API key` -> `Artifacts section`. Desktop checks
  find exactly one `section[aria-label="Artifacts"]`, `Artifact sort`, `Search
  artifacts`, and `Grid view` inside it; clicking `Grid view` changes
  `aria-pressed` from `false` to `true`. At `390x844`, compact layout hides the
  workspace review panel visually but keeps the DOM label as `Artifacts`, with
  no page-level horizontal overflow and no framework overlay. Screenshots:
  `/tmp/agi-desktop-artifacts-section-browser.png` and
  `/tmp/agi-desktop-artifacts-section-mobile.png`.
- Browser plugin page identity succeeds for the Workspace Tool events section
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype wraps event activity in `section[aria-label="Tool events"]`,
  and the desktop Tool events panel now exposes the same region label.
  QA used the manual-runtime path: `Use API key` -> More workspace tabs ->
  `Tool events`. Desktop checks find exactly one
  `section[aria-label="Tool events"]`, the All event filter, Search events, and
  Auto-scroll control inside it; clicking the All filter keeps
  `aria-pressed="true"`. At `390x844`, compact layout hides the workspace
  review panel visually but keeps the DOM label as `Tool events`, with no
  page-level horizontal overflow and no framework overlay. Screenshots:
  `/tmp/agi-desktop-tool-events-browser.png` and
  `/tmp/agi-desktop-tool-events-mobile.png`.
- Browser plugin page identity succeeds for the visible Tool events naming
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype uses the visible section heading `Tool events`, while the
  desktop workspace event surface still showed `Background agents`. Desktop now
  uses `Tool events` for the signed-out workflow shortcut, More workspace tabs
  item, selected workspace tab, panel heading, and empty state. QA verified the
  signed-out `Tool events 0` shortcut exists with zero `Background 0` shortcuts,
  then used `Use API key` -> More workspace tabs -> `Tool events`; desktop checks
  find exactly one `section[aria-label="Tool events"]`, visible heading
  `Tool events`, selected tab `Tool eventsidle`, and `No tool events` empty
  state with no visible `Background agents` text. At `390x844`, the connected
  compact layout keeps the selected Tool events DOM state with no page-level
  horizontal overflow or framework overlay, and the signed-out mobile shortcut
  remains reachable as `Tool events 0`. Screenshots:
  `/tmp/agi-desktop-tool-events-label-browser.png`,
  `/tmp/agi-desktop-tool-events-label-mobile.png`, and
  `/tmp/agi-desktop-tool-events-shortcut-mobile.png`.
- Browser plugin page identity succeeds for the Runtime monitor health-metrics
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype's Local Rust Core card exposes `Version`, `Uptime`, `CPU`,
  `Memory`, and `Workers`; the desktop Runtime monitor now adds the same health
  metric group while keeping existing Live / Scope / Events / Queue status
  tiles. QA used the manual-runtime path: `Use API key` -> sidebar Runtime
  monitor. Desktop checks find exactly one `Runtime monitor` region and one
  `Runtime health metrics` group with `Version 0.3.1`, `Uptime 2h 14m`,
  `CPU 18%`, `Memory 4.6 / 15.8 GB`, and `Workers 8 / 16`, with zero expected
  mismatches. At `390x844`, compact layout hides the sidebar visually but keeps
  the runtime health metrics in DOM, with no page-level horizontal overflow and
  no framework overlay. Screenshots:
  `/tmp/agi-desktop-runtime-health-metrics-browser.png` and
  `/tmp/agi-desktop-runtime-health-metrics-mobile.png`.
- Browser plugin page identity succeeds for the Board runtime-target option
  naming parity pass, and Browser console has no warnings/errors, but Browser
  DOM snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype labels the Board toolbar staging target as `Remote staging`,
  while the desktop Board command-bar select still displayed `Staging Runtime`.
  Desktop now keeps the internal option value `Staging Runtime` but renders it
  as `Remote staging` only inside the Board command bar. QA used the
  manual-runtime path: `Use API key` -> `Runs section` / Board. Desktop checks
  find exactly one Board `select[aria-label="Runtime target"]` with visible
  options `Local Rust Core` and `Remote staging`; selecting the staging value
  changes the selected value to `Staging Runtime` and selected text to
  `Remote staging`. This pass scoped the command-bar value/display split; the
  following pass covers the titlebar Runtime option naming. At `390x844`, the
  Board command-bar select keeps the same option mapping in DOM, with no
  page-level horizontal overflow and no framework overlay. Screenshots:
  `/tmp/agi-desktop-board-remote-staging-browser.png` and
  `/tmp/agi-desktop-board-remote-staging-mobile.png`.
- Browser plugin page identity succeeds for the topbar Runtime option naming
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype labels the titlebar Runtime staging option as `Remote staging`,
  while desktop still rendered `Staging Runtime` from the shared command-bar
  runtime labels. Desktop now keeps command surfaces on the internal
  `Staging Runtime` value path, but renders the titlebar
  `select[aria-label="Runtime"]` staging option and Runtime monitor card title
  as `Remote staging`. QA used the manual-runtime path: `Use API key` ->
  titlebar Runtime -> `Runs section` / Board. Desktop checks find exactly one
  titlebar `Runtime` select, zero titlebar `Runtime target` selects, titlebar
  options `Local Rust Core` and `Remote staging`, and selecting `staging`
  changes the selected text plus Runtime monitor title to `Remote staging`.
  Board command-bar checks still report option text `Remote staging` with value
  `Staging Runtime`. At `390x844`, the compact layout hides the titlebar select
  visually but keeps the same DOM option mapping and Runtime monitor title, with
  no page-level horizontal overflow and no framework overlay.
  Screenshots: `/tmp/agi-desktop-titlebar-runtime-remote-staging.png` and
  `/tmp/agi-desktop-titlebar-runtime-remote-staging-mobile.png`.
- Browser plugin page identity succeeds for the Board run-time tick parity pass,
  and Browser console has no warnings/errors, but Browser DOM snapshot still
  fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Source comparison found the web prototype
  renders the current run tick as a concrete time label such as `00:18:42`,
  while desktop still hard-coded the emphasized tick as `Now`. Desktop now passes
  the selected run time into Board and sanitizes empty or `never` fallback values
  to `00:00`, keeping the `Now marker` setting label separate from the rendered
  time scale. QA used the manual-runtime path: `Use API key` -> `Runs section` /
  Board. Desktop checks find exactly one `Run graph time scale`, strong tick
  text `00:00`, and no `Now` or `never` text inside the time scale. At
  `390x844`, the same tick mapping remains in DOM with no page-level horizontal
  overflow and no framework overlay. Screenshots:
  `/tmp/agi-desktop-board-runtime-tick.png` and
  `/tmp/agi-desktop-board-runtime-tick-mobile.png`.
- Browser plugin page identity succeeds for the Human decision context parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Source comparison found the web prototype's
  Human decision Context section uses `Related issue`, `Tests`, and `Checks`,
  while desktop still showed generic runtime-derived defaults `Artifacts`,
  `Events`, and `Plan fields`. Desktop now derives the same three context labels:
  issue from task metadata or task id, tests from task/plan metadata when
  present, and checks from plan metadata, errors, or available review signals.
  QA used the manual-runtime path: `Use API key` -> Workspace `Changes`.
  Desktop checks find exactly one `.review-decision[aria-label="Human decision"]`
  and context labels `Related issue`, `Tests`, `Checks`, with zero old default
  context labels. At `390x844`, the same context labels remain in DOM with no
  page-level horizontal overflow and no framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-context.png` and
  `/tmp/agi-desktop-human-decision-context-mobile.png`.
- Browser plugin page identity succeeds for the Human decision action-copy parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Source comparison found the web prototype's
  Human decision action area labels the section `Choose an action`, the approve
  action `Approve patch`, the approve helper `Apply changes and continue the
  run`, and the request helper `Provide feedback to the agent`, while desktop
  still used generalized review wording. Desktop now uses the prototype action
  copy without changing the existing run-scope checkbox, `Snooze` button, or
  disabled action guards. QA used the manual-runtime path: `Use API key` ->
  Workspace `Changes`. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]` action panel with
  `Choose an action`, `Approve patch`, `Apply changes and continue the run`,
  `Request changes`, `Provide feedback to the agent`, `Apply to this run only`,
  and `Snooze`, with no scoped `Mark this review as accepted` or
  `Keep the workspace paused for revision` text. At `390x844`, the same
  action-copy labels remain in DOM after the manual-runtime flow while the
  Workspace panel follows the mobile hidden-panel rule; the fresh mobile shell
  smoke has no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-actions.png` and
  `/tmp/agi-desktop-human-decision-actions-mobile.png`.
- Browser plugin page identity succeeds for the Human decision status-badge
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype uses impact/resolution status language in the Human decision
  heading badge: pending shows `High impact`, and any resolved decision shows
  `Resolved`. Desktop now shows data-derived `<risk> impact` while pending and
  `Resolved` after approval or requested changes, leaving the decision history
  labels (`Approved`, `Changes requested`) unchanged. QA used the manual-runtime
  path: `Use API key` -> `Create new run` -> Workspace `Changes` ->
  `Approve patch`. Pending checks find exactly one
  `.review-decision[aria-label="Human decision"]`, badge text `Low impact`, no
  `Pending` label, and an enabled approve action. After clicking `Approve
  patch`, desktop checks find heading `Decision recorded`, badge `Resolved`, no
  `Approved` badge label, and a decision history row labelled `Approved`. At
  `390x844`, the same resolved badge remains in DOM while the Workspace panel
  follows the mobile hidden-panel rule, with no page-level horizontal overflow
  or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-status-badge.png` and
  `/tmp/agi-desktop-human-decision-status-badge-mobile.png`.
- Browser plugin page identity succeeds for the Human decision request-source
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype renders `Request from Executor` under the `Human decision`
  kicker before the decision title. Desktop now renders the same request-source
  line in the Human decision heading without changing the requester section or
  action controls. QA used the manual-runtime path: `Use API key` ->
  `Create new run` -> Workspace `Changes`. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]`, visible source text
  `Request from Executor`, and header order `Human decision` ->
  `Request from Executor` -> `Review background activity`, with badge
  `Low impact`, no framework overlay, and no page-level horizontal overflow. At
  `390x844`, the same request-source text remains in DOM while the Workspace
  panel follows the mobile hidden-panel rule, with no page-level horizontal
  overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-request-source.png` and
  `/tmp/agi-desktop-human-decision-request-source-mobile.png`.
- Browser plugin page identity succeeds for the Human decision heading parity
  pass, and Browser console has no warnings/errors, but Browser DOM snapshot
  still fails with `incrementalAriaSnapshot is not a function`; rendered QA used
  Browser locator/evaluate checks. Source comparison found the web prototype's
  pending Human decision title is fixed to `Approve patch`, then changes to
  `Decision recorded` after approval or requested changes. Desktop now uses the
  same pending heading while keeping the data-derived review detail in the body
  copy. QA used the manual-runtime path: `Use API key` -> `Create new run` ->
  Workspace `Changes` -> `Approve patch`. Pending checks find exactly one
  `.review-decision[aria-label="Human decision"]`, heading `Approve patch`,
  source `Request from Executor`, badge `Low impact`, no old dynamic heading
  `Review background activity`, and body copy `New run #1 queued with local
  runtime.`. After clicking `Approve patch`, desktop checks find heading
  `Decision recorded`, badge `Resolved`, and an `Approved` history row. At
  `390x844`, the resolved heading remains in DOM while the Workspace panel
  follows the mobile hidden-panel rule, with no page-level horizontal overflow
  or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-heading-pending.png`,
  `/tmp/agi-desktop-human-decision-heading.png`, and
  `/tmp/agi-desktop-human-decision-heading-mobile.png`.
- Browser plugin page identity succeeds for the Human decision copy/summary
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype separates the status explanation from a `Summary` section:
  pending copy reads `The agent wants to apply the following patch to the
  repository.`, approved copy reads `The run can continue with the retry patch
  applied to the local workspace.`, and contextual patch details sit under
  `Summary`. Desktop now uses the same status-copy layer while preserving the
  data-derived review summary in a separate `Summary` section. QA used the
  manual-runtime path: `Use API key` -> `Create new run` -> Workspace `Changes`
  -> `Approve patch`. Pending checks find heading `Approve patch`, badge
  `Low impact`, decision copy `The agent wants to apply the following patch to
  the repository.`, and `Summary` text `New run #1 queued with local runtime.`.
  After clicking `Approve patch`, desktop checks find heading
  `Decision recorded`, badge `Resolved`, decision copy `The run can continue
  with the retry patch applied to the local workspace.`, `Summary` text
  `Patch approved. Executor can continue the run.`, and an `Approved` history
  row. At `390x844`, the same resolved copy and summary remain in DOM while the
  Workspace panel follows the mobile hidden-panel rule, with no page-level
  horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-copy-summary-pending.png`,
  `/tmp/agi-desktop-human-decision-copy-summary-resolved.png`, and
  `/tmp/agi-desktop-human-decision-copy-summary-mobile.png`.
- Browser plugin page identity succeeds for the Human decision context-heading
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype renders a visible `Context` heading above `Related issue`,
  `Tests`, and `Checks`, while desktop previously exposed the context grid
  without a visible section label. Desktop now wraps the context grid in a
  `Context` section while preserving the data-derived context values. QA used
  the manual-runtime path: `Use API key` -> `Create new run` -> Workspace
  `Changes`. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]`, visible heading `Context`,
  one `.decision-context-grid`, labels `Related issue`, `Tests`, and `Checks`,
  no framework overlay, and no page-level horizontal overflow. At `390x844`, the
  same `Context` heading and labels remain in DOM while the Workspace panel
  follows the mobile hidden-panel rule, with no page-level horizontal overflow
  or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-context-heading.png` and
  `/tmp/agi-desktop-human-decision-context-heading-mobile.png`.
- Browser plugin page identity succeeds for the Human decision diff-format
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype renders the Human decision `Insertions / Deletions` value with
  slash-separated diff text like `+45 / -12`, while desktop still emitted
  `+n -n`. Desktop now formats review diff summaries as `+n / -n`, including
  the empty `+0 / -0` state. QA used the manual-runtime path: `Use API key` ->
  `Create new run` -> Workspace `Changes`. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]`, the risk-strip label
  `Insertions / Deletions`, value `+0 / -0`, no scoped `+0 -0` value in the
  strip, no framework overlay, and no page-level horizontal overflow. At
  `390x844`, the same diff value remains in DOM while the Workspace panel
  follows the mobile hidden-panel rule, with no page-level horizontal overflow
  or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-diff-format.png` and
  `/tmp/agi-desktop-human-decision-diff-format-mobile.png`.
- Browser plugin page identity succeeds for the Human decision action-header
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype's Human decision action area renders only the visible
  `Choose an action` heading above the action buttons, while desktop still
  showed an extra state-dependent helper line (`Updates review and selected
  run`, `Updates workspace packet only`, or `Waiting for workspace context`).
  Desktop now removes that extra helper line while preserving `Approve patch`,
  `Request changes`, `Apply to this run only`, `Snooze`, and decision history.
  QA used the manual-runtime path: `Use API key` -> `Create new run` ->
  Workspace `Changes`. Desktop checks find exactly one
  `.review-decision[aria-label="Human decision"]`, `.decision-actions-panel`
  header text `Choose an action`, zero non-heading children in the action
  header, none of the old helper strings, no framework overlay, and no
  page-level horizontal overflow. At `390x844`, the same action header remains
  in DOM while the Workspace panel follows the mobile hidden-panel rule, with
  no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-action-header.png` and
  `/tmp/agi-desktop-human-decision-action-header-mobile.png`.
- Browser plugin page identity succeeds for the Human decision file-delta
  plumbing pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype's Human decision Files list renders per-file delta values such
  as `+38 / -8` at the right edge of each file row, while desktop previously
  collapsed that value into generic file metadata. Desktop review artifacts now
  carry a structured `diff` field and Human decision file rows prefer
  `artifact.diff` before falling back to `meta` or `tracked`; pull request file
  rows keep the same structured field for later parity work. QA used the
  manual-runtime path: `Use API key` -> `Create new run` -> Workspace
  `Changes`. The live default run has no file artifacts, so rendered checks
  verify the non-regression path: exactly one
  `.review-decision[aria-label="Human decision"]`, the Files section still
  shows `No changed files detected.`, zero `.decision-file-row` rows, no
  framework overlay, and no page-level horizontal overflow. Static build checks
  against `index-DWbbCsJ3.js` confirm the source/build carry the new
  `diff -> meta -> tracked` branch. At `390x844`, the same empty Files section
  remains in DOM while the Workspace panel follows the mobile hidden-panel rule,
  with no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-file-delta-default.png` and
  `/tmp/agi-desktop-human-decision-file-delta-mobile.png`.
- Browser plugin page identity succeeds for the Human decision no-requester
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype flows from `Summary` directly to `Files`, then `Agent reasoning`
  and `Context`, while desktop still inserted an extra `Requester` section even
  though the drawer header already shows `Request from Executor`. Desktop now
  removes the redundant `Requester` section and the unused requester summary
  field while preserving the header source line. QA used the manual-runtime
  path: `Use API key` -> `Create new run` -> Workspace `Changes`. Desktop
  checks find exactly one `.review-decision[aria-label="Human decision"]`,
  visible source `Request from Executor`, section order `Summary` -> `Files` ->
  `Agent reasoning` -> `Context`, no `Requester` section, no `Workspace agent`
  requester copy, no framework overlay, and no page-level horizontal overflow.
  At `390x844`, the same section order remains in DOM while the Workspace panel
  follows the mobile hidden-panel rule, with no page-level horizontal overflow
  or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-no-requester.png` and
  `/tmp/agi-desktop-human-decision-no-requester-mobile.png`.
- Browser plugin page identity succeeds for the Human decision empty-history
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype's default Human decision action area does not render an empty
  decision-history section, while desktop still showed `Decision history` /
  `No local decision recorded.` before any local action. Desktop now renders
  `.decision-history` only when records exist, preserving the local audit trail
  after a decision while removing the empty-state copy from pending reviews.
  QA used the manual-runtime path: `Use API key` -> `Create new run` ->
  Workspace `Changes`. Desktop pending checks find exactly one
  `.review-decision[aria-label="Human decision"]`, exactly one
  `.decision-actions-panel`, required action text `Choose an action`,
  `Approve patch`, `Request changes`, `Apply to this run only`, and `Snooze`,
  zero `.decision-history` nodes, no `Decision history` text, no
  `No local decision recorded.` text, no framework overlay, and no page-level
  horizontal overflow. After `Approve patch`, `.decision-history` appears with
  one `.decision-history-row.approved` row containing `Approved`, with no
  framework overlay or page-level horizontal overflow. At `390x844`, a freshly
  rebuilt pending panel keeps the same no-empty-history DOM state while the
  Workspace panel follows the mobile hidden-panel rule, with no page-level
  horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-human-decision-history-empty.png`,
  `/tmp/agi-desktop-human-decision-history-approved.png`, and
  `/tmp/agi-desktop-human-decision-history-empty-mobile.png`.
- Browser plugin page identity succeeds for the local-run artifact fixture
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype seeds a new local run with concrete artifact fixtures:
  `0002-retry-backoff.patch`, `runner.rs`, `test_retry.rs`, and
  `run-report.md`, while desktop manual-runtime `Create new run` previously
  produced an empty Files section. Desktop local runs now seed timeline
  artifact items for the retry patch, two changed files, and the generated run
  report. The Human decision view uses source-file artifacts before patch or
  report artifacts, so `Files changed` is `2`, total diff is `+45 / -12`, file
  rows are `runner.rs` with `+38 / -8` and `test_retry.rs` with `+7 / -4`,
  and `0002-retry-backoff.patch` plus `run-report.md` stay out of the decision
  Files list. The Artifacts tab shows four rows, including patch/file/report
  row type labels, previews, sizes, diffs, footer total `26.4 KB`, and the
  prototype-matching default selection `0002-retry-backoff.patch`. Its filter
  bar matches the web
  prototype for this fixture (`All`, `Files`, `Patches`, `Reports`, `Logs`) and
  omits the desktop-only `Events` filter when no Events artifacts exist; the
  `Reports` filter narrows to one `run-report.md` row. QA used the
  manual-runtime path: `Use API key` -> `Create new run` -> Workspace
  `Changes` -> `More tabs` -> `Artifacts`.
  Desktop checks find exactly one Human decision panel, exactly two
  `.decision-file-row` rows, no `No changed files detected.` empty state, no
  framework overlay, no page-level horizontal overflow, and zero console
  warnings/errors. Artifact row meta uses prototype singular type labels
  (`Patch`, `File`, `File`, `Report`) while preserving plural filter labels.
  At `390x844`, the mobile section menu can open the Artifacts review stage;
  the visible stage contains the same four rows, singular row type labels,
  plural filter labels, footer total, and default selected patch, with no
  page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-local-run-artifacts-changes.png`,
  `/tmp/agi-desktop-artifact-row-type-labels.png`,
  `/tmp/agi-desktop-local-run-artifact-filters-parity.png`,
  `/tmp/agi-desktop-local-run-artifacts-report.png`,
  `/tmp/agi-desktop-local-run-artifacts-report-filter.png`, and
  `/tmp/agi-desktop-artifact-row-type-labels-mobile.png`.
- Browser plugin page identity succeeds for the local-run background-event
  fixture parity pass, and Browser console has no warnings/errors, but Browser
  DOM snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype seeds Tool events with `executor.apply_patch`, `filesystem.write`,
  `git.diff`, Executor reasoning, and Planner feedback, while desktop manual
  runtime `Create new run` previously exposed only a queued-run message. Desktop
  local runs now seed seven background events: 3 Tools, 2 Reasoning, and
  2 Messages. The Human decision `Agent reasoning` now reads
  `Patch applied cleanly. Next: run unit tests to validate...` from the local
  reasoning event instead of repeating the queued-run system message. QA used
  the manual-runtime path: `Use API key` -> `Create new run` -> Workspace
  `Changes` -> `More tabs` -> `Tool events`. Desktop checks find
  `.review-background[aria-label="Tool events"]`, badge `7 of 7`, prototype
  filter labels `All`, `Tools`, `Reasoning`, `Messages`, and `System`, no
  zero-count `Errors` filter, aria count labels `All events, 7 available`,
  `Tools events, 3 available`, `Reasoning events, 2 available`,
  `Messages events, 2 available`, and `System events, 0 available`,
  visible rows for `executor.apply_patch`, `filesystem.write`, `git.diff`,
  Executor reasoning, and Planner feedback, no framework overlay, no page-level
  horizontal overflow, and zero console warnings/errors. Clicking the `Tools`
  filter reduces the list to exactly three Tool rows with latencies `412 ms`,
  `98 ms`, and `77 ms`. At `390x844`, the Tool events DOM still contains the
  three filtered rows while the Workspace panel follows the mobile hidden-panel
  rule, with no page-level horizontal overflow or framework overlay. Screenshots:
  `/tmp/agi-desktop-local-run-events-changes.png`,
  `/tmp/agi-desktop-local-run-tool-events-filter-labels.png`,
  `/tmp/agi-desktop-local-run-events-background.png`,
  `/tmp/agi-desktop-local-run-tool-events-filter-labels-tools.png`, and
  `/tmp/agi-desktop-local-run-tool-events-filter-labels-mobile.png`.
- Browser plugin page identity succeeds for the local-run agent-lane Board
  parity pass, and Browser console has no warnings/errors, but Browser DOM
  snapshot still fails with `incrementalAriaSnapshot is not a function`;
  rendered QA used Browser locator/evaluate checks. Source comparison found the
  web prototype's Run graph groups Timeline work by agent lanes (`Planner`,
  `Researcher`, `Executor`, `Verifier`) and seeds 15 task pills, while desktop
  manual-runtime `Create new run` still used status lanes. Desktop Flow/Timeline
  with `Agent layout` set to lanes now renders the prototype lane model and
  uses `AGENT` as the time-scale label. Desktop local runs seed all prototype
  task labels: `Plan`, `Decompose`, `Assign`, `Replan`, `Search docs`,
  `Collect context`, `Synthesize`, `Checkout repo`, `Apply patch`, `Run tests`,
  `Build`, `Queue (2)`, `Static analysis`, `Test verify`, and `Report`. QA used
  the manual-runtime path: `Use API key` -> `Create new run` -> Runs > Board ->
  select `Apply patch` -> `More tabs` -> `Tool events`. Desktop checks find
  `.board-shell`, status `15 visible`, four `.lane` rows, 15
  `.task-timeline-pill` controls, lane counts `Planner 4`, `Researcher 3`,
  `Executor 4`, and `Verifier 4`, no framework overlay, no page-level horizontal
  overflow, and zero console warnings/errors. The `Apply patch` pill carries
  the prototype dashed styling (`task-timeline-dashed`, 2px dashed border)
  while the other seeded executor pills remain solid. Selecting `Apply patch`
  updates the selected timeline pill, changes the Human decision summary to
  `QA seed for Apply patch`, shows `Related issue LOCAL-RUN-1` and
  `Tests 6 / 7 passed`, and appends a Tool events row with
  `Apply patch selected in Timeline.`. At `390x844`, the Board remains
  visible at 374px wide, the DOM still contains all four agent lanes and 15 task
  pills, a geometry check reports zero overlapping pill pairs after adding the
  agent-lane internal track width, the Workspace review panel follows the mobile
  hidden-panel rule, and `documentWidth` / `bodyWidth` remain 390 with no
  overlay. Screenshots: `/tmp/agi-desktop-board-dashed-apply-patch.png` and
  `/tmp/agi-desktop-board-dashed-apply-patch-mobile.png`.

### Open

- Browser plugin DOM snapshot is still unstable in this environment
  (`incrementalAriaSnapshot is not a function`), so Browser validation used
  locator checks, read-only DOM evaluation, and screenshots rather than full
  Browser DOM snapshots.
- Browser plugin tab binding later timed out twice while inspecting the mutated
  edge-case tab, resetting the Node browser session. The same flows were then
  verified with independent Playwright runs against the current Vite server.
- Native GUI login was not password-typed by the agent; verification used the
  local preset and contract-backed browser flow because manual password entry is
  treated as a secret-bearing UI action.
- Computer Use still launches or binds to an old debug `.app` bundle when asked
  generically for `agi-stack Desktop`. Explicitly targeting the rebuilt release
  `.app` path captures the current source UI.
- Computer Use returned `cgWindowNotFound` when recapturing the release app
  immediately after clicking the command-palette button. The app process stayed
  alive; command-palette behavior and accessibility were verified in Browser and
  Playwright instead.
- Agent runtime completion after `ack/send_message` still depends on local LLM
  provider configuration and worker health; this pass verifies the desktop
  request path reaches a real Agent conversation.
