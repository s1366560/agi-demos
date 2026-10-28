# Persistent Computer Use

This document describes the macOS implementation added on 2026-10-22. Browser
support covers Chrome, Edge, the Electron in-app browser, and attached MCP Apps.
It does not provide OpenAI's private browser services. MCP remains a structured
host tool interface; there is no invented `cua.connectors` or `cua.mcp` namespace.

## JavaScript runtime and authority

`cua_repl_js`, `cua_repl_reset`, and `cua_repl_add_module_dir` use a packaged Node
runtime and the original implementation in `agi-stack/packages/cua-repl`.
The interpreter supports persistent bindings, top-level await, imports, timers,
text, images and audio. `cua` supplies app and browser discovery, selection and
operations. Initial entrypoints emit their documentation and applicable state.
`emit: false` suppresses observations without suppressing first-use documentation.

The sidecar owns the interpreter and assigns every RPC a fresh step identity.
JavaScript cannot supply its tenant, project, conversation, run, device, claim,
plugin generation or approval. Native and browser calls enter the same scoped
tool hosts as ordinary tools. MCP App callbacks enter exact MCP tool authority;
permission to inspect a DOM never grants permission to execute its tools.

Normal turns retain interpreter state for the same conversation, selected device
and effective sandbox. Reset destroys variables, module caches and pending work
while retaining validated module-directory registrations and existing apps/tabs.
Adding a module directory restarts the interpreter to apply its filesystem grant.
Stop, timeout and revoked authority terminate the interpreter and managed children.

A permission request suspends its pending Promise. Resuming with the identical
code restores that pending step under fresh authority; preceding JavaScript and
completed actions are not replayed. Generic one-use approval binds the step UUID,
canonical tool and arguments. A user pause preserves the cell but rejects an
interrupted operation on explicit continuation without resending it. Unknown
post-dispatch outcomes cannot be retried as though nothing happened.
After a human response is committed, the model receives its structured request,
target, action, scope and response receipt. That context does not grant authority;
the scoped host still validates and consumes the exact approval.

Permission requests travel in a separate host result field bound to the original
tool, arguments, engine session, cell and step. Application data containing an
`error` or `permission_required` property cannot create a pending approval. The
argument digest uses RFC 8785 canonical JSON without changing existing approval
keys or receipts. Only a matching trusted gate that has not dispatched the action
can restore its one-use permission; a transport error cannot restore it.

## Operating-system sandbox

macOS Seatbelt confines the packaged Node process. Read-only and workspace-write
profiles permit runtime/workspace/module reads and a private temporary directory;
only workspace-write grants workspace writes. Full access permits broader file
and remote-network operations while protecting application control data, vaults,
host/runtime code and loopback control endpoints. The process inherits a fixed
environment rather than provider secrets or application credentials.

Direct forks, detached children, alternate executable replacement and raw native
process creation are denied by the OS. Supported asynchronous child-process
operations use a host broker, and each owned child receives the same sandbox.
Nested process trees and synchronous child-process APIs are not promised. Failure
to apply the sandbox is an error; execution never falls back to an unsandboxed VM.

## Browser and MCP behavior

Browser references preserve provider and tab identity. Browser selection does
not create a tab; existing-tab selection rejects ambiguous or stale references.
Chrome/Edge extension operations and Electron IAB operations share the facade
while preserving origin consent and full-CDP policy. The facade includes DOM and
accessibility observations, locators, cross-origin frames, shadow DOM, input,
navigation, viewport/visibility, file selection, downloads, annotated screenshots,
tab management and declared provider capabilities. Documentation is based on the
implemented provider rather than an empty success response for unsupported work.
Browser results retain their types: text reads return strings, including text
that looks like JSON, and evaluated objects may contain an ordinary `error` field.

Workspace-only configuration updates preserve browser settings. Explicitly
stopping the bridge closes existing WebSocket sessions, cancels pending requests
and invalidates the old backend instances. A reconnecting native broker rereads
the private registry and token; it cannot reuse the stopped generation's handles.

File selection is limited to canonical authorized roots and rejects protected
application files. Downloads stay in an owned directory and are reported after
actual completion. Browser authentication pins origin and document identity;
password fields and QR confirmation are presented to the human. Secret values
and protected QR imagery do not enter model observations.

MCP tools, resources, templates and prompts use actual protocol requests with
pagination. Manual MCP OAuth reuses the existing PKCE, callback and encrypted-vault
flow. MCP App frames bind the server revision, catalog, frame instance and actual
run authority. Detach, scope changes and revocation reject late callbacks.
An authorized callback returns its result to the originating iframe without
opening a replacement App. Its host-private context binds the live registration,
server and exact tool; ordinary model tool calls still open their declared App.
Model-visible MCP tools that require write approval remain discoverable under
restricted profiles. Discovery does not grant execution: the exact call still
passes the current profile and one-use permission checks. App-only tools remain
outside the model catalog.
Ordinary cloud MCP calls pin the exact server/tool binding in their device claim;
App-only tools remain restricted to their authorized callback path.

## Cloud execution

The existing authenticated selected-device channel carries the three REPL tools.
The Python and Rust backends authorize every inner device step against the real
run, selected agent, device epoch, exact arguments, target and catalog. The desktop
consumes a short-lived single-use receipt before dispatch. A known `not_sent`
native permission response can release that receipt for the same pending step;
transport failures and unknown outcomes cannot.
Both servers validate the separate permission record against the authenticated
claim and stored inner step. Device results cannot issue a server-side MCP
permission. A result that arrives after its claim changes is rejected.

Human approval can resume the same cell under a new outer claim without replaying
earlier code. Empty MCP allow-lists remain empty. Child execution uses its own
identity and tool profile, and cannot borrow the parent's registered App frame.
The synchronous child execution path still reports awaiting-input explicitly
where its enclosing subagent runtime cannot suspend for a human response.

## Audio and lock continuity

Microphone, system-audio and mixed capture have separate approval. Starts accept
an integer duration of 100–300000 ms; the facade defaults to 60000 ms. Native
exports use 24 kHz, stereo PCM16 WAV. Recording receipts survive export retry;
pause, stop, timeout and authority loss stop capture rather than silently restart
it. Media playback reads bounded owner-scoped chunks and rejects a changed MIME
type or invalid offset. JavaScript receives bytes only for authorized attachments.
Stopping an owned recording does not require another generic write approval.
It retains the current run, session, recording-owner and parameter checks, and
cannot select an arbitrary export destination.

Python cloud providers declare exact model IDs through
`Provider.config.audio_input_models`; the list defaults to empty and is validated
against the configured model roster. The Rust server's environment-backed LLM
uses `AGISTACK_LLM_AUDIO_INPUT_MODELS`, a JSON array matched against the selected
model; its Provider API also validates stored declarations. Model names never
imply audio capability. OpenAI-compatible input accepts WAV or MP3; Anthropic
audio input is currently unsupported.

Automatic audio requires an actual broker-owned artifact and matching live owner,
conversation, engine session, run revision and device authority. Unsupported or
invalid attachments are omitted before model submission with an explicit host
explanation, while their timeline and playback artifacts remain available.
Explicit user audio fails closed when unsupported. Authority loss during queueing,
requests or streaming cancels the operation and prevents late results. Python
releases the waiting limiter slot and closes its owned HTTP transport; Rust drops
the pending upstream operation.

Lock continuity uses a full-screen cover and controlled temporary unlock, followed
by relocking. The setting says this explicitly. Signed installer, authorization
plugin, guardian, helper and independent watchdog participate in the flow. Each
enable requires fresh one-use native consent; session and persistent grants cannot
authorize it. A short lease belongs to the current run and live REPL cell. Renewal
cannot outlive pause, completion or revoked authority. Physical takeover suppresses automatic
unlock. Relocking is observed before removing the cover; a killed cover process
can expose the desktop briefly until the OS relocks, so zero-exposure guarantees
are not claimed.

Installation and removal run through the native Settings UI and macOS administrator
authorization. Availability is a live probe of OS permissions, signatures,
configuration and authorization rules. Installation transactions preserve unrelated
authorization branches and recover after interrupted phases. A privileged installer
must consume a one-use activation from the live signed helper, bound to the exact
request, operation and generation. Forward transaction writes recheck that helper;
late administrator approval after cancellation or helper exit cannot restart an
expired transaction. Rollback remains available after cancellation. Production signing
and notarization remain release requirements; local development signatures do not
establish production distribution readiness.

## Validation performed

Executable tests exercise the packaged Node interpreter, sandbox restrictions,
pending-step continuation, cloud HTTP authorization, real stdio MCP, Chromium DOM
and frame operations, actual downloads, file selection, protected authentication,
and annotated screenshot pixels. Native component tests exercise audio lifecycle,
lock supervision and interrupted installation rollback. These tests use controlled
identities and fixtures where indicated; they do not establish a remote production
deployment or every browser/OS combination.

The 2026-10-26 permission-provenance regression groups passed 227 Rust tests
across the core result contract, local authority and REPL, browser/native consent,
MCP Apps, and both cloud-side device paths. The Python groups passed 169 tests;
the new permission-result module reached 98.67% line coverage and the four
measured transport/permission modules reached 87.44% combined. Cases include
reserved error strings returned as ordinary data, exact-step approval and denial,
policy input transformations, prior effects surviving same-cell continuation,
unknown transport outcomes retaining consumed permits, and changed or expired
claims rejecting late permission records. The full Rust workspace also passed
`cargo check --workspace --all-targets`, with unused-code/import warnings.
These are executable regression results; the updated native callback and cloud
mixed journeys remain pending.

The IAB input regression dispatches through a real Chromium target and verifies
trusted click/submit, checkbox, wheel and keyboard effects. Accessibility tests
include body/output text and hidden-content exclusions. MCP callback lifecycle
tests use a real stdio fixture to verify consecutive callbacks, stable frame
registration, pagination and invalidation, alongside exact-tool authorization
and pending-step resume/cancellation tests. These do not replace the model-driven
native browser and iframe acceptance runs.

On 2026-10-23, the canonical native client recovered its browser bridge with
Chrome's existing native-host process still running. The formal runtime reported
Chrome, Edge and IAB connections. Refreshing the workspace preserved the enabled
configuration, registry generation and Chrome connection. After restoring the
task-owned Edge application's complete vendor-signed bundle, both existing
Chrome and Edge native-host processes also survived a UI bridge off/on cycle:
off removed the registry/socket and all connected backends; on created a new
registry generation and restored Chrome, Edge and IAB without restarting either
browser or native host. The related bridge, native-host and configuration-patch
regression suites passed 62 tests. This does not establish complete native
browser interaction or live stale-handle rejection.

On 2026-10-26, a sidecar recovery gap was corrected: the Electron supervisor now
restores only browser configuration acknowledged by the current process before
exposing the replacement sidecar as ready. It does not replay runs or claims.
Fourteen new regressions and eleven existing supervisor tests passed, including
configuration races, failed restoration and a delayed handshake after shutdown.
In the canonical native14 client, the operator enabled the bridge, verified all
three backends, and terminated only that client's sidecar with SIGKILL while no
run was executing. Electron remained alive, spawned a new sidecar and restored
Chrome, Edge and IAB connections. The native settings page then showed the bridge
enabled and connected on port 9765. This verifies recovery within one Electron
process; a new application launch retains the existing default-off behavior.

The native14 manual HTTP MCP OAuth journey also passed against a task-owned
loopback authorization server. Cancelling the first connection performed no
token exchange. A new connection completed discovery, dynamic registration,
S256 PKCE, resource binding and the real browser callback; the native Test action
then discovered one tool. After the 30-second token lifetime, a second Test
automatically refreshed the credential and still succeeded. The server recorded
two rotating refreshes across the journey. Disconnect marked the native account
unconnected, disabled the server and produced one successful revocation. The
temporary registration, browser tab and fixture process were then removed.

A real model request also discovered the registered MCP fixture's exact
`render_main` tool, requested one-use permission and successfully rendered its
App. The following App-handle authorization flow did not complete: both that run
and a separate IAB run hit the workspace model route's fixed 45-second timeout.
Rendering alone does not establish callback or iframe acceptance.

After removing that timeout obstruction, a fresh native run exposed a separate
App-frame registration failure. The renderer assigned an iframe name after
navigation, while CDP retained the old name. Registration now follows the exact
host DOM node's frame ID and verifies its direct ancestry and document identity.
The frame-boundary suite passed 15 tests, including a real dynamically renamed
cross-origin frame, sibling substitution rejection and same-URL reload expiry.
The native callback and catalog checks still require a successful rerun.

Local providers now persist a per-request timeout, defaulting to 45 seconds and
bounded at 300 seconds. Workspace routing and an explicitly selected conversation
model use the same timeout wrapper. Pause and Stop interrupt an in-flight model
request, including response headers, partial JSON and partial SSE, and preserve
the appropriate paused or cancelled checkpoint. HTTP integration tests verify
upstream closure and reject stale run-control revisions. In the 2026-10-23 native
client, the QA provider's connection test passed and its timeout was saved as
120 seconds. A real IAB run entered Paused immediately through the native control
and resumed under the same run ID. That run created one IAB tab, resumed each
approved operation without replaying the cell, and produced both an accessibility
snapshot and screenshot showing `IAB_NATIVE_OK | trusted=true`. It then exhausted
its round budget before final completion; it is not recorded as a completed run.

The later native12 hidden-IAB run exposed a separate failure: an inactive
WebContentsView had a 0-by-0 viewport. Text fill succeeded, but the Save click
was rejected as obscured and produced no input events. The REPL screenshot then
timed out; the subsequent budget exhaustion did not establish task completion.
An independent Electron 43 reproduction confirmed the zero-sized viewport and
hidden-renderer input issue. Hidden views now retain a nonzero viewport and detach
from their host; a temporary, invisible, nonfocusable window initializes their
Chromium viewport and is immediately destroyed. Six real Electron scenarios
passed trusted mouse input, form submission, JPEG capture and continued rejection
of covered elements, including a new hidden tab, an inactive tab, hide/show,
viewport override/reset and no existing host. All three initialization windows
were destroyed, with no show or focus events. The focused Node suites passed four
tests with one explicit skip; Rust input-scope tests passed eight cases and
Electron TypeScript compilation passed. The corrected path still requires a
canonical native rerun; the failed click was not retried.

The canonical native13 rerun reached browser selection, then stopped before tab
creation because the model's repaired permission action contained a duplicate
`rationale` field. A separate MCP App run rendered the main frame, obtained its
one-use claim and read the real count of zero, but its next model request timed
out after 120 seconds before any click. Both runs remain failed; neither proves
the pending IAB interaction or MCP callback acceptance. The provider's formal
model discovery returned alternative model IDs, including MiniMax-M3.1-Flash
and MiniMax-M2.7. On native14, a fresh conversation selected the enabled Flash
model while provider and workspace defaults remained M3. Prepared requests
confirmed Flash. Its structured Once request succeeded; an attempted REPL call
before plan approval was correctly blocked. After the operator approved the
three-step plan with WorkspaceWrite, the single browser-selection cell succeeded
and the model finished. Native review marked this short canary complete. It
opened no tab and does not establish input or screenshot acceptance.

The following full IAB Flash run reached a newly created tab but did not execute
the Save click: its task-owned HTTP fixture was no longer listening, and Electron
reported `ERR_CONNECTION_REFUSED`. The tab fell back to `about:blank`; locating
the input timed out. The model's later attempted navigation remained unapproved
when the round budget expired. This failed fixture run is not browser acceptance.

A fresh IAB conversation on the canonical native24 launch completed on
2026-10-26. The first automatic snapshot of the single hidden tab already
contained the expected controls. After separate exact-step approvals, the same
input cell returned the requested saved text and exactly one trusted click on
`qa-save`. Its updated diagnostics reported a 1200-by-800 viewport. The next cell
captured a 2400-by-1600 JPEG; the existing owner-scoped preview endpoint returned
the actual image, which was visually checked against the saved text. The native
review action marked the run completed. The provider, workspace policy and
16-round budget were unchanged. The model did not update individual plan-task
statuses, so the completed run and those stale task fields remain distinguishable.

The native14 main window later stopped repainting while its accessibility tree
continued updating. Reload produced a white frame; restarting through the
canonical Make target restored the visible UI. Two separate Electron 43.2.0
reproductions compared 54 OS/window snapshots with changing DOM counters across
hidden initialization, failed navigation, reload and resize, without reproducing
the failure. Its cause remains unresolved; no speculative rendering fix was made.

On native15, the persisted MCP Flash plan rendered the real main App once and
the UI displayed count zero before REPL approval. The first `getTab` still failed
with `browser is unavailable`, and fresh inventory returned no browsers. The
rendered App retained the earlier run revision after a generic tool approval
advanced the run, so strict scope matching excluded it from discovery. The case
ended incomplete, with no Increment click or backend increment dispatch; the
owned App tab was then closed. This is a reproduced approval-continuation defect,
not a successful callback test.

Ordinary tool approval now transfers only existing live App attachments to the
resumed revision after the authenticated approval and exact run transition have
committed. The iframe and public target identity remain stable across cells;
old callback continuation history is cleared, and each new callback still needs
its own authorization. The focused MCP automation suite passed 19 tests,
including the formerly failing HTTP-to-public-inventory path, a real Node
variable retained across separate cells, invalid approval and scope changes,
closed/reset surfaces, cancellation, server and plugin-generation changes, and
the existing exact-step and cloud continuations. The test DOM response is
scripted, so a fresh canonical native callback run remains required.

The next native16 attempt failed before rendering the App: its model-generated
RequestHuman ID, `approve-render-main-once`, collided with a persisted request
from another conversation. The formal run ended failed with no pending request,
and the fixture audit showed no render or increment dispatch. This exposes a
separate HITL identity-isolation defect; it does not test the attachment fix.

Fresh desktop RequestHuman actions now receive a host-bound ID before validation,
answer lookup, observation and checkpoint persistence. Its deterministic scope
includes the conversation, run or message category, engine and round; a later
request cannot reuse an earlier answer merely by repeating the model's label.
Persisted pending requests retain their original ID during recovery, including
legacy requests. The desktop HITL suite passed 29 tests, including six new
engine, HTTP, restart and binding cases; the 19 MCP automation tests and 10 core
HITL/suspension compatibility tests also passed. The corresponding Rust cloud
message-execution binding passed four new tests, including three using the
task-isolated PostgreSQL database, plus 18 existing HITL, outer permission and
WebSocket tests. These checks do not establish the pending cloud native journey.

Native17 displayed and accepted the new host-bound request IDs, rendered the
main App with count zero, then still returned `browser is unavailable` from the
prescribed first REPL cell. No claim or increment callback was reached. After
the operator denied the model's unrelated native-app observation request, the
run ended explicitly incomplete. Source inspection found a missing registration
sequence: opening the App during NeedsApproval cannot attach its earlier
revision, while generic continuation only migrated already-attached tabs. A
regression for first attachment after approval was added; the earlier 19-test
suite attached its test surface before entering NeedsApproval.

The resulting mount lifecycle uses an immutable host-generated nonce for each
iframe attachment. Pending mounts can survive a granted generic approval without
acquiring an operation permit. Cleanup, renderer reload and late registration
responses retire only their own nonce; both queued DOM operations and App
callbacks carry their captured nonce and reject a replacement frame before
dispatch. Regression tests reproduced a stale callback reaching the real stdio
fixture before this check and verified zero dispatch afterwards. The final 25
Rust MCP automation tests, one cloud MCP compatibility test and 36 Electron/React
tests passed, including real StrictMode and Chromium/OOPIF cases. Renderer and
Electron type checks also passed. Native18 is the subsequent live validation;
these automated checks alone do not establish its result.

Native18 again displayed the real main App with count zero but its first exact
`getTab` returned `browser is unavailable`. The model stopped immediately with
an incomplete result and made no increment or recovery attempt. The native log
showed successful Electron frame resolution followed by repeated Rust
`mcp_app_scope_mismatch` during the resumed run. Read-only inspection confirmed
that the actual Canvas used React StrictEffects. A combined regression reproduced
cleanup before first attachment after the waiting engine's weak authority had
expired: the canceled first mount prevented migration and the replacement mount
could not register. The fix records the host's local-authority variant when the
App opens and validates persisted conversation/run ownership, generation and
catalog before admitting only a waiting mount identity. Actual attachment and
operations still require fresh authority. The formal HTTP regression now covers
expired authority, canceled first mount, replacement pending registration,
generic approval, fresh attachment and the first public `getTab` claim followed
by exact Once approval and same-cell DOM output. All 28 MCP automation tests and
the real stdio cloud compatibility test passed. Closing before a replacement
registers still prevents renewal. Native19 is the subsequent live validation;
these automated checks alone do not establish its result.

Native19 reached the exact `tab.claim` permission and resumed its original cell
after Once approval, then stopped on `mcp_app_frame_unavailable` before returning
the initial DOM state. The App remained visible with count zero and no increment
was dispatched. Read-only runtime status confirmed the browser bridge was still
disabled after launch, with no connected backends. The claim path needs only the
App registry; the following DOM read also requires the IAB bridge. This run did
not establish a new frame-lifecycle defect. Subsequent native templates check
that bridge enablement and the IAB connection are ready before creating a task.

Native20 ran with the bridge enabled and connected. Its first public `getTab`
returned the actual App DOM after exact claim approval. The browser click then
suspended for its own Once approval, followed by a distinct Once request for
`increment_main`. The real stdio audit recorded exactly one increment, with a
new operation ID, and persisted counts changed from main 0 / sibling 0 to
main 1 / sibling 0. The App still displayed count zero and its old receipt:
Electron had timed out the pending `mcp_app_operation` response after 30 seconds.
The control loop also awaited that callback serially, preventing later control
commands from progressing while approval was pending.

The same cell separately failed with `repl_result_before_operations_settled`.
Its actual code waited only for an already-existing nonempty status element to
be attached, which did not establish callback completion. The runtime correctly
rejected a result while its external operation remained unsettled. A later
read-only receipt attempt found that the failed kernel's variable no longer
existed. The operator denied a subsequent rebind request, and the run finished
explicitly incomplete without another increment. Initial App binding and one
backend dispatch are verified; same-cell receipt delivery and screenshot
completion remain unverified. Follow-up work must preserve the unsettled-result
guard, propagate callback cancellation, and wait for a newly completed receipt.

The follow-up correction keeps approval-bound callbacks pending until completion
or cancellation, while the private control channel continues serving lifecycle
requests. Cancellation targets the host-generated request and exact App mount;
its acknowledgement follows the actual callback-future drop. Missing confirmation
reports an unknown outcome rather than a successful cancellation. Pending and
backpressured callbacks remain bounded at 32.

The installed MCP SDK also ignored cancellation for legal request IDs `0` and
`""` because it used a truthiness check. A version-specific pnpm patch for SDK
1.29.0 changes both ESM and CommonJS builds to ignore only a missing ID. Eighteen
regressions use the actual AppBridge and SDK Server to verify abort delivery,
suppression of late results/errors, distinct numeric/string IDs, and harmless
unknown or completed-request cancellation. All eighteen pass after the patch.

The native24 approval-aware fixture run completed on 2026-10-26 in a fresh
canonical native25 Electron launch. Generic rendering and REPL approvals were
followed by separate exact App-claim, button-click and backend-callback grants.
The same 1,593-character action cell resumed unchanged across both action gates:
its actual baseline was 1, the displayed result was 2, and the new main-side
receipt reported `duplicate: false`. The stdio audit recorded exactly one
`increment_main` call for operation `6c85599b-661a-4849-9121-12aa663e0555`;
the sibling counter stayed at 0. The cell produced a real 109,722-byte PNG,
retrieved through its owner's artifact-preview endpoint and visually checked.
The native run was approved as completed at revision 14, then its App was closed
and its original temporary session signed out.

The action cell spanned 132.423 seconds including approvals; the callback itself
did not remain pending for 120 seconds, so this run does not establish that
specific wait duration. The screenshot contains the correct App result but also
includes a host activity overlay where it overlaps the App rectangle: current
capture crops the composited host page and does not isolate iframe pixels.
The successful REPL result has an artifact descriptor, while the current tool
details presentation initially omitted its inline image/audio preview. The later
mixed-media correction is described below; screenshot scope remains separate.

The native26 catalog/prompt conversation completed on the same canonical
native25 launch. Its 2,240-character action cell resumed unchanged after the
single catalog-click approval and printed a fresh receipt with four resources,
three resource templates and three prompts. The typed prompt contained the
expected user text and an assistant resource with the exact URI, MIME type and
text. The server audit recorded two requests for each list, preserving the
opaque second-page cursors, followed by `prompts/get` for `describe_receipt`.
Both counters and the two existing operations remained unchanged at 2/0. The
run completed at revision 12, its App was closed, and its original temporary
session was signed out. Resource content reads and expanded-template reads
remain separate from this catalog verification.

The independent resource-read fixture was registered through the native settings
UI and passed its real stdio handshake. Its first task stopped before either
data read: an extra model-authored check required initially empty URI output
elements to be visible. The exact check reproduced offline; all required IDs
existed and both action buttons were visible and enabled. The server audit
contained only rendering and the UI HTML read. This attempt is incomplete and
does not establish static or expanded-template resource reads.

A subsequent native29 attempt explicitly waited for the operator to open the
App and verify its SDK connection before requesting separate REPL permission.
It still failed before either data read: the replacement iframe could not
register while the run waited for an ordinary clarification. An old mount's
cleanup then excluded the App from the later revision renewal. The mount
registry now admits a verified pending identity during both `NeedsInput` and
`NeedsApproval`; it does not expose a browser handle or permit App operations
until the existing response and current-authority checks succeed. Formal
HTTP/Node regressions cover the original failure and independent claim consent,
plus close, reset, server changes, generation changes and replacement races.
All 32 formal resume tests passed in the main workspace after the correction.

On 2026-10-27, a fresh native30 conversation passed the real resource-read flow.
The App mounted during the ordinary clarification, then the independent REPL
approval and exact claim-step approval resumed the original cell successfully.
The unchanged static and template cells each resumed their own pending click,
validated a new full receipt and returned successfully. The server recorded
exactly one read of the static URI and one read of the expanded template URI,
in addition to the single render and UI HTML load. The template cell emitted
text followed by its scoped PNG. The actual 1276-by-590 PNG contained only the
App viewport, with no host chat, panel controls or computer-use overlay. The
viewport clipped part of the receipt; complete content was verified from the
same cell's text and the server records. The run completed with no pending
requests, its App was closed and its original temporary session was signed out.
An earlier native30 retry remained incomplete after the operator opened the
Activity panel during a pending click, retiring the App attachment. Its expired
handle dispatched neither data read; that retry is not counted as a read pass.

The preceding catalog attempt timed out in the model before its action cell;
it made no catalog requests. A separate cross-App negative test also remained
incomplete: after an operator clarification, the unchanged action cell returned
`mcp_app_scope_mismatch` before the expected click approval. The server received
only rendering and UI-resource requests, with no sibling callback. That scope
failure does not establish the intended `mcp_app_tool_not_visible` rejection;
clarification continuation and the negative test require a repair and rerun.

The repair subsequently passed 28 formal resume tests and a fresh native27
conversation on the canonical native26 launch. The same App handle survived one
ordinary clarification (`needs_input` revision 9 to `running` revision 10), then
read the current status, receipt and count before requesting its exact click
permission. The 1,911-character action cell resumed unchanged and returned the
expected `mcp_app_tool_not_visible` refusal. The displayed count stayed at 2 and
the receipt was unchanged. The independent stdio audit contained only the new
`render_main` and UI-resource read, with no `increment_sibling` request; persisted
counters remained 2/0 and both existing operation receipts were unchanged.
No sibling backend approval was requested. The run completed at revision 14,
then its exact App was closed and its original temporary session signed out.

A fresh native30 hidden-tool case on 2026-10-27 also passed. The public App
binding and the single `Try hidden tool` click each resumed their original
cell after their own exact Once approval. The 1,896-byte action cell returned
`mcp_app_tool_not_visible`, with count 2 unchanged and the same displayed
receipt. The server audit added only one `render_main` and one UI-resource read;
there was no `hidden_probe` dispatch, and the full persisted counter and
operation state was unchanged. No hidden-tool backend approval was requested.
The run reached review with no pending requests, was marked complete, and its
exact App was closed.

The native30 App-switch case also passed with separate render and claim
approvals for main and sibling. After the sibling was selected and its public
binding returned the sibling DOM, one read through the retained original main
handle failed with `mcp_app_frame_expired`. It did not retarget to the selected
sibling. The server recorded only the two renders and their UI-resource reads;
all counters and operation receipts remained unchanged. No callback was run.
Both App tabs were closed after the run was marked complete. This establishes
old automation-handle retirement, not destruction of the hidden guest document.

The native30 reset case passed while the original App remained selected and
mounted. It recorded the actual attachment ID and one fresh DOM snapshot,
executed the separately approved `cua_repl_reset` once, then used that literal
old ID in the first new cell. The public `getTab` call returned
`browser is unavailable`; it neither reacquired by URI nor invoked a callback.
The model requested additional generic Once approvals for the baseline read
and post-reset probe, staying within the existing run budget. The server audit
added only one render and one UI-resource read, with all persisted counters
and operation receipts unchanged. This verifies attachment revocation, not
destruction of the still-mounted guest or cancellation of a pending callback.

The native30 pending-callback close case then verified real cancellation. After
one label fill and one Increment click, the original cell paused on the exact
backend callback permission. The operator verified non-dispatch in the server
audit and closed that App through the native tab control. The same pending
request remained visible; granting it resumed the unchanged cell, which caught
`repl_callback_cancelled_before_dispatch`. The server received no increment,
and the full counter and operation state stayed unchanged. A preceding cell
had failed at parse time with `Illegal return statement` and no outputs; its
correction ran before any App action. A tab-ID typo in the click request's
descriptive text did not change its verified step ID or bound arguments.

The native30 server-disable case reached the exact pending `increment_main`
callback after one fill and one click in the unchanged 3,967-character cell.
The operator opened normal account settings, verified the same formal pending
request and the still-connected fixture, then disabled that exact server.
Its native card changed to disabled and its owned stdio process exited. The
original request remained available; its Once response resumed the same cell,
which caught `mcp_app_pending_cell_changed`. The full server state remained
unchanged, the new operation ID was absent, and the audit added only rendering
and the UI-resource read. No increment reached the server. This establishes
non-dispatch through the complete normal Settings-disable path. Formal pending
state does not establish callback liveness at the intermediate Settings step,
and the returned error combines several authority failures; disabling alone was
not isolated as the exclusive cause. The model reported that limitation without
another probe. The run was reviewed, its App closed and its owner signed out.

The resulting error-fidelity fix keeps failed local callback continuations out
of the Cloud candidate path. Local callbacks now preserve the disabled-server,
catalog-change and expired-frame reasons, with an explicit scope-mismatch error.
All 48 callback lifecycle tests passed, including a real Node/MCP callback that
was approved through HTTP, then disabled before dispatch: the original cell
continued once, returned `local_mcp_server_disabled`, and produced no server
effect. Cloud continuation tests remained green. This automated result has not
yet been repeated in a rebuilt native Electron client.

A separate real Node/HTTP/WebSocket regression reproduced an in-flight receipt
read failing after the approval revision changed. Only structured, read-only
`mcpapps` operations are now suspended and admitted again under current authority.
The old bridge waiter is removed, late results are discarded, and the original
Node cell, RPC and step remain intact. Writes and external callbacks are not
replayed. The result guard also includes suspended reads. The focused Rust groups
passed 112 tests; Electron/SDK checks passed 52 tests with real Chromium frame
cases enabled. Native receipt completion still requires the fresh App rerun.

Two additional failures selected by a broad Rust name filter were investigated
and corrected. Marketplace installation verification now uses a private lease
for the registered Candidate or Active generation, while ordinary tool, resource
and App access remains Active-only. The lease covers every catalog page and its
storage update. Thirteen focused tests passed, including the original resource
read overlapping uninstall and the candidate's non-publication boundaries.
The signed-subagent fixture now configures its parent through the formal API
before starting and supplies the production agent boundary. Its positive and
stale-selection negative tests both passed without changing product permissions.

Native21 successfully resumed its first App binding cell, but the next model
request exceeded the unchanged 120-second provider timeout before any click.
Native22 used a shorter reference cell and reached its first receipt read, where
`JSON.parse(await locator.innerText())` failed because the public JS wrapper had
already parsed the returned text. Both runs retained main 1 / sibling 0, made no
new increment, and ended without a successful receipt or screenshot. Their Apps
were closed and their original test sessions disposed before restarting.

The browser operation wrapper now preserves the RPC result's original type.
JSON-looking DOM text remains text, and application objects containing an `error`
field remain data at this JS boundary; transport failures still reject through
the RPC error channel. The public package passed 35 tests, including real Node
JSONL and Chromium DOM serialization under four browser-provider identities.
The unchanged reference cell also passed 26 offline tests through the complete
public facade. A separate authenticated WebSocket bridge to the production
authority, media decoder and sandboxed Node reproduced the native error with the
old staged SDK and passed after staging the fix. Its exact claim grant is inserted
by the test fixture; it is not an additional HTTP approval test. These tests do
not establish a live MCP callback's completion.

Native23 passed the original text-read boundary, claimed the real App and reached
both the browser click and the exact backend callback permission. The owned
fixture's private 120-second timer then expired while human approval was pending.
The operator denied the late callback; the formal run finished incomplete and
the backend retained main 1 / sibling 0 with no new operation. Its App was closed
and its original session disposed. A new, isolated fixture copy keeps only the
interactive increment promise pending for approval; ordinary requests retain
the deadline and send the standard cancellation notification. Nineteen offline
tests verify its exact-response, stale-message and page-close behavior. These
fixture tests do not establish native callback completion or host cancellation.

Separate Chrome and Edge runs created one tab each and completed the authorized
fill and screenshot operations. Both returned from the locator click without
saving: their accessibility snapshots and screenshots still showed `Not saved`.
Those runs reached review with the failed check reported explicitly. The failure
was reproduced through the public Rust facade with an ordinarily launched,
vendor-signed Chrome 155: hidden tabs accepted mouse packets without delivering
button events. Chromium input now serializes each tab's input sequence and
temporarily enables renderer focus emulation when hidden. Cleanup releases held
input and restores the prior state; failed releases remain queued and must
succeed before later input. Full-CDP Input/Focus requests share the same lock.
The regression passed against signed Chrome 155.0.8059.85 and Edge 155.0.4283.62,
including trusted save, cancellation, restoration, preserved preexisting focus
emulation, and unchanged active tab, window state and foreground application.
The browser crate passed 119 unit and two integration tests. A subsequent native
Electron launch exposed a debug-build stack overflow in the browser's nested
async input guard, even when selecting a browser for a read. Boxing the operation
before constructing that guard reduced the public dispatch future from 28,224 to
3,152 bytes. Public browser reads now pass on both 2 MiB and 256 KiB worker stacks;
a size-bound regression rejects the former allocation. The next canonical
Electron run successfully saved `CHROME_NATIVE11_OK` and `EDGE_NATIVE10_OK`; each
page recorded exactly one trusted click on its Save button. Edge also captured
its screenshot and reached review. Chrome produced a viewable screenshot, but
the following model request failed with `vision_invalid_artifact`: the bare JPEG
bytes emitted by the REPL were incorrectly registered as PNG. Chrome's input
check passed, while screenshot delivery and final completion require a rerun
after the media-boundary correction. Bare image emission now identifies PNG,
JPEG and WebP from their encoded bytes. The Rust boundary also verifies the
declared type against the encoding and fully decodes the image before storing
it. The correction passed 30 Node tests, three media tests, two tests spanning
the real Node kernel, browser host, scoped artifact store and HTTP model request,
and four HTTP vision tests. Artifact ownership validation remains enforced.
The canonical native12 rerun then bound the exact existing Chrome tab and
emitted its screenshot through `tab.screenshot()` and bare `emitImage`. The
artifact was correctly stored as JPEG, the model received it and reported the
saved text plus one trusted click, and the run was reviewed and completed in
the native UI. No input was replayed during this verification.

On 2026-10-26, a separate real Flash-backed REPL cell emitted four text entries,
two actual App screenshots and one explicitly synthetic 440 Hz, one-second WAV
in interleaved order. The first native inspection exposed a stale parent CSP
hash that blocked the result renderer. The hash now matches the exact shipped
guest script; CSP was not relaxed. Seventeen renderer, browser and CSP tests
passed. After a canonical Electron restart, the same persisted output displayed
text, image, text, audio, text, image and text in that order. Native playback
changed from Play to Pause and then returned to Play at 0:01. This verifies
persisted mixed-media rendering and playback, not physical audio capture.
The screenshots still contain a composited host activity overlay; screenshot
pixel isolation remains a separate unresolved check.

A separate native local mixed run reached review after retrieving the real
native application inventory, reading the exact Chrome fixture tab through the
REPL, and querying the registered stdio MCP fixture's counts. Each requested
permission was approved once. The browser retained its saved text and single
trusted click; the MCP query returned main=0 and sibling=0. This verifies the
local mixed observation path, not native input or either cloud execution path.

The native9 MCP rerun registered the real iframe but exposed a second failure:
approving the pending tab claim advanced the run revision while the App retained
its previous scope. Local continuation now binds the committed positive approval
to the actual pending REPL cell and step before updating that App's execution
revision. Normal browser requests still reject an old scope; only the captured
callback may follow the explicitly approved revision lineage. Reset and module
registration invalidate the matching session's App handles without revoking a
sibling execution. The real stdio callback and scope regressions pass; the native
claim, callback and catalog rerun remains pending. Three additional integration
tests cross the authenticated HTTP approval handler with real Node and stdio MCP
processes. They verify exact-once callback continuation in the original iframe,
forged or expired step rejection, and denial without callback dispatch. This
full path also exposed excessive stack usage from nested REPL task-local futures.
Boxing their operation reduced the scoped future from 175,320 to 9,176 bytes;
the three tests pass with the default thread stack and a 16 KiB size bound.

The native8 composer Stop probe exposed an unhandled local WebSocket stop
message: the UI displayed a stopping state, but the run continued to review.
The correction binds local execution cancellation to the rendered run ID and
revision, and planning cancellation to the exact message ID. Cloud conversations
retain their existing WebSocket protocol; stale requests and late receipts cannot
target a successor execution.

A fresh canonical native9 launch on 2026-10-23 passed the Stop rerun. The approved
read-only task selected IAB through the public `cua.getBrowser` entrypoint, then
started a second cell waiting on a 25-second timer. Clicking Stop Response at
12:48 while that tool was running immediately displayed Cancelled. The formal
run `local-run-ad1365a4-3009-4843-a2e8-87b85e6a84fb` was cancelled at revision 3,
and the `cua_repl_js` observation reported `repl_cancelled`. A second read at
12:56 retained that run ID, revision and cancelled status, with no late
`STOP_TIMER_COMPLETED` output or Resume action. This establishes native composer
Stop for the exercised local REPL path.

The combined Rust authority and cancellation suite passed 87 tests, including
owner logout and workspace changes, retained capabilities, idle and racing runs,
real Node children, held HTTP/SSE responses and exact planning-turn WebSocket
cancellation. Unrelated same-user session logout and same-scope refresh preserve
the owning execution. Frontend Stop/socket tests passed 45 cases and desktop
shell tests passed 52; renderer and test TypeScript compilation also passed.
Browser audit tests passed 36 cases, covering the bound Edge backend and authorized
origin, failure without a second origin query, credential-fill auditing and fresh
authorization reads on consent retries. Owner logout and workspace-switch
cancellation have not yet been verified through the native9 UI.

The Node REPL/facade coverage run passed 27 tests with 93.22% line coverage,
84.16% branch coverage and 67.55% function coverage across nine source modules.
The aggregate line-coverage target of 80% passed; this does not claim that every
file or metric reaches 80%, nor measure the separate CLI process, browser DOM
scripts, Rust or Swift. Retained-capability tests also check the kernel's internal
in-process reset; the desktop's public reset continues to destroy the Node process.

The 2026-10-22 cloud-audio checks passed 265 Python tests, including 49 new audio
cases, and 84 Rust server tests, including 11 new audio cases. Python tests sent
verified WAV bytes through the actual LiteLLM adapter to loopback HTTP endpoints
in normal and streaming modes. Python and Rust tests also held real HTTP/SSE
responses open, revoked authority and verified upstream closure or response-body
cancellation. Additional cases cover exact capability declarations, forged or
changed artifacts, session/run isolation, device disconnection, native Pause/Stop
and cancellation while waiting for model admission.

These tests use controlled authority, native-result and artifact fixtures. They
establish the exercised wire format and cancellation behavior, not physical
recording, a remote model's understanding of audio, or production end-to-end
acceptance across all three execution paths.

The canonical Electron launch used `make -C agi-stack run-desktop` with the task's
QA profile and an existing Apple Development identity. Its UI reported granted
Accessibility, Input Monitoring, Screen Capture, microphone and system-audio
permissions. An actual MiniMax-backed run completed native inventory and two
persistent cells whose counter advanced from 1 to 2.

Three real audio sources completed capture, export, playback and restart playback.
Later native checks verified source-consent denial and independent recording stop
while the parent run continued. See [native audio validation](native-audio-validation.md)
for the observed results and remaining boundaries.

The first lock-component installation request expired before administrator
authorization completed. A fresh request on 2026-10-23 completed after the human
authorized macOS installation; the native probe reported the component installed
and not running. After explicit action-time confirmation, the isolated project's
lock capability was enabled in the native UI on 2026-10-23. The component remained
not running and the owned fixture's input stayed empty. Actual temporary
unlock/relock and native lock fault-injection
acceptance remain pending; installation, component tests and development signatures
do not establish those results.
