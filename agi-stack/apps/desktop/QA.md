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
