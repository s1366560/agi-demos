# Desktop Computer Use implementation

The first-party `memstack-computer-use` v2 plugin supplies scoped native tools, its
runtime skill, native services, settings, and structured results. The existing
`computer_*` names remain supported. This document describes the implementation
and the limits of the validation performed; it is not a release approval gate.

The persistent Node facade, browser operations, MCP Apps, cloud step authorization,
audio export and lock continuity added on 2026-10-22 are described in
[Persistent Computer Use](computer-use-repl.md).

## Runtime and authorization

- `agi-stack/crates/adapters-cua` owns authenticated `MemstackComputerUseIPC-3`
  inherited pipes, numbered concurrent requests, cancellation, helper supervision,
  observation coordinates, and typed media. Credentials do not use arguments,
  environment variables, or a shared RPC socket. A partially transmitted action
  whose result is lost is not automatically replayed.
- `agi-stack/apps/desktop/sidecar/src/local_runtime/computer_use_v2` owns plugin
  instances, application grants, execution identities, scoped artifacts, connector
  accounts, and native HITL receipts. Disabling revokes authority before cleanup;
  uninstall removes the owning instance's grants and temporary resources.
- Calls bind user, tenant, project, device, conversation, run, and native session.
  Applications use canonical identities and executable/signature digests; consent
  freezes the resolved process. Observation and screenshot access also require
  grants. Once, run-session, and persistent grants remain distinct.
- Input references the observed window and snapshot. `coordinate_space` defaults
  to logical window coordinates; `screenshot` uses actual image pixels. Decoded
  image dimensions and the captured window bounds determine the conversion.
  A submitted input consumes its observation; subsequent input must re-observe.
  Missing snapshots, stale windows, focus failures, and unavailable capabilities
  return explicit errors.
- Policy, run ceilings, native grants, and OS permissions all apply. Semantic
  risk assessments remain structured agent decisions. Connector effects are
  declared metadata: closed native operations or exact MCP tool annotations in
  `x-cua-operation-effects`; unknown operations require mutation permission.
  Managed accounts and configured external MCP servers have separate identities.
  External servers require the selected agent's actual allow-list. A declined
  connector request blocks desktop fallback in that trusted run.
- Native Calendar, Contacts, and Messages grants have separate service identities.
  Connector mutations require a one-use grant for the exact pending operation and
  input, even when a broader account read grant exists. Persistent or session
  grants cannot authorize these actions. The consent UI exposes only the scopes
  that the pending operation supports.
- A structural HITL validation port checks native pending ownership, run/session
  identity, capability, tool, and current authority before a request can suspend
  the model. Fabricated, changed, foreign, or expired native requests produce a
  bounded model observation instead of an unanswerable approval card. Generic
  requests and already answered resumption remain compatible.

## Background input and input presentation

See [macOS background input](macos-background-input.md) for the trusted input modes,
PID/window routing, generation and recovery rules, authenticated telemetry,
native acceptance results, and verified compatibility limits.

## Cloud sessions

The authenticated `/api/v1/agent/ws` device channel carries announcements,
heartbeat, request IDs, results, and bounded media chunks. The desktop main
process receives requests, claims each through authenticated HTTP, and invokes
the private sidecar pipe. Renderer code cannot fabricate a native device result
or claim. Desktop vault credentials remain local.

`src/infrastructure/agent/native_computer_use` implements the production Python
bridge using Redis records and streams. Requests are durable across API workers;
claiming consumes one request only after fresh user/project/run/workspace/child
authority validation. Stop, cancellation, disconnect, and native rejection close
the bound device work. Per-turn tool contributions are user scoped rather than
project-cache scoped. Native grants pause through the existing persisted HITL
coordinator; resumption preserves the exact native binding.

`agi-stack/apps/server/src/computer_use_device_v2` provides the Rust server
equivalent. Its foundation agent runtime is narrower than the Python processor.
Persisted custom agent definitions supply scoped tool/MCP allow-lists, pinned to
the run and rechecked on claim. Default/builtin profiles without a shared
authoritative MCP definition do not receive external configured MCP access.

HTTP/WebSocket/Redis integration tests exercise scoped claims, human resumption,
and typed image delivery with controlled identities and native protocol fixtures.
The 2026-10-15 acceptance used real macOS Electron in cloud mode, a local Python
development backend and the existing remote MiniMax-M3 visual Provider. Native
application consent, the application icon and target-window preview, a visual
click, repeated fresh observations, Pause, fresh-authority Resume and Stop were
exercised through the client. This validates the development cloud-to-device
path; it is not a remote production-server, Windows or Linux acceptance result.
The detailed run results and cleanup are recorded below.

Screenshots and audio use artifact storage. Transcript attachments are optional
for compatibility with old sessions. OpenAI and Anthropic requests contain real
image content blocks; request/trace logs retain references and redacted image
metadata rather than base64. Audio previews are bounded; full recordings remain
owned artifacts. Microphone, system audio, and mixed recording are separately
authorized, stopped on termination, and not reconstructed by replaying start.
Each recording start requires a one-use grant. A recovered native session must
obtain new consent for a new recording; its logical continuation cannot reuse a
previous recording grant.

Both cloud backends connect owned recording artifacts to model input under
explicit audio capability and current execution authority. Python resolves durable
artifact references after actual provider/model selection; the Rust server wraps
its selected LLM with broker-bound audio authorization. Request and trace logs
retain references or redacted metadata rather than inline audio bytes.
Configuration, cancellation semantics and the 2026-10-22 controlled HTTP/SSE
results (265 Python and 84 Rust tests) are documented in
[Persistent Computer Use](computer-use-repl.md).

## Native implementations

The desktop presentation includes native menu-bar/tray status, per-session
pause/resume/stop, target application icons, and the latest authorized window
preview. macOS uses the helper's AppKit status item; Windows and Linux use the
Electron tray. Consent, session activity, settings and scoped tool-result views
show the same canonical application identity and decorative icon. Icons are
copied into owned artifacts from the verified native process; model observations
contain screenshot media, not decorative icon attachments.

Previews identify their target window and observation time. Status refreshes do
not capture additional frames. Native status notifications carry the complete
registered session owner context; foreign and invalid notifications cannot change
another session. Main-process status polling validates mode/scope and rejects
stale callbacks after authority changes. Opaque renderer guests receive bounded
image bytes and create their own Blob URLs under the inherited desktop CSP.

Pause concerns the owned computer session and releases held input, clipboard and
recording resources while invalidating observations. Resume requires a live,
running parent task and current plugin/owner authorization, then requires a fresh
observation. It does not restart recording. If the parent task is paused or has
ended, the menu directs the user to the formal task controls. Stopped sessions
cannot resume. An explicit cloud Resume requests fresh authority through
`POST /api/v1/agent/device/requests/{request_id}/resume-authority`. Both server
implementations require a successful completed invocation, its original owner,
device and engine session, current authorization revision and a running parent;
cancelled requests and terminal parents are rejected. The 30-second response
permits only native-session resumption and bounds resource cleanup. It leaves the
original invocation and result unchanged, never replays an action or recording,
and does not replace the fresh claim required for a later tool call.
Background connectors continue to require their independent permissions.

Native cancellation recovery cannot reset a paused or terminal session. A new
authorized session requires the normal begin/owner flow. macOS ordinary GUI
operations report `screen_locked` when the native session dictionary reports a
locked screen; capabilities report that state without attempting to unlock.
Critical AX window-list reads preserve system error categories and do not replace
the cached list with an empty list after a failed read. A successful empty list
still invalidates disappeared windows.

Linux exposes a bounded `ax_tree` from the observed AT-SPI hierarchy, with the
same snapshot/window identity as the screenshot and text. The common adapter
validates node indexes, parent relationships, coordinates and limits before
delivery. Native backend references are excluded; protected text values are
redacted. Roles and relationships come from the native provider, without
classification from application text.

| Platform | Backend | Current validation boundary |
| --- | --- | --- |
| macOS | Swift AX, ScreenCaptureKit, CoreGraphics, native WAV capture, EventKit/Contacts/Messages adapters | Actual two-window fixture, screenshot dimensions, Chinese input, focus/stale rejection, cancellation, held-input release and clipboard crash recovery pass. Electron lifecycle, native consent and real Provider screenshot-to-click-to-observation acceptance pass for the larger visual fixture. |
| Windows | Dedicated COM UIA worker, Windows Graphics Capture, SendInput, WASAPI | Cross compilation and linking performed. No interactive Windows desktop was available. |
| Linux X11 | Native AT-SPI, XComposite window capture, XTEST, GIO application registration, clipboard ownership, PipeWire Pulse-compatible audio through GStreamer | 29 native Xvfb/GTK checks, one missing-Composite rejection, nine input-fault cases and 13 resource-fault cases pass. Current checks include application icons, window metadata, the actual AX hierarchy and password redaction, cancellation recovery, terminal reset rejection, held-input release and clipboard restoration on pause, and fresh observation after resume. Distinct XI2 source simulation exercised; physical hardware remains unverified. |
| Linux Wayland | AT-SPI, RemoteDesktop/ScreenCast portal, PipeWire, EIS, supported data-control clipboard | Code and protocol checks; no corresponding compositor/portal session was available. Missing portal/EIS/clipboard support returns explicit capability reasons. |

macOS uses a separate signed input watchdog. Windows and Linux use a resource
guardian and a separate input worker; each surviving process has the input
ownership information needed to recover from its peer's failure. Private pipes
carry acknowledged input claims and validate actual parent process identities.
Owned holds release on EOF or lease failure, deferring releases for separately
tracked external sources. A stopped main process is terminated before its input
lease is released, so resuming it cannot send delayed input.
Native device leases exclude competing helper processes on the same login desktop.
Simulated input-source tests do not substitute for physical takeover acceptance.

The local Electron acceptance reused the existing MiniMax-M3 Provider and its
application vault. A disposable two-window fixture drew randomly ordered large
colored shapes without accessibility child labels. The model selected Fixture 1,
obtained actual screenshot pixels, clicked the blue circle, and observed
`clicked:blue:circle`. An independent native UI observation confirmed that status
and no held Shift key or mouse button. No hidden layout file, random seed or click
coordinate was supplied to the model. Its second click reused the consumed
snapshot and was rejected; a subsequent fresh observation confirmed the first
click. Earlier small-target attempts missed, and a separate run hit the existing
45-second model-candidate timeout. This acceptance demonstrates the visual
execution chain; it does not establish reliable fine-target positioning for this
Provider.

macOS tracks tagged events through a listen-only input tap and reports Input
Monitoring separately. System aggregate key/button tables are not used to classify
physical versus synthetic events. Its signed child owns clipboard writes and
baseline restoration; the surviving parent checks the child's exit and the exact
clipboard generation/owner marker before using its recovery mirror. Native
clipboard clearing and writing are separate OS operations: simultaneous faults
before a commit marker cannot guarantee restoration without risking overwriting
the user's intervening clipboard change.

X11 clipboard recovery uses XFixes writer-close and ownership generations. It
preserves later user copies and explicit clears, including a guardian crash after
a real server-grab acknowledgement. Windows synchronizes the all-format baseline
before writing and uses an exact committed owner/sequence marker for recovery;
faults between preparation and commit have an unknown outcome. Wayland reports
`clipboard_crash_recovery=unavailable`: the current protocol does not provide a
verified cross-process selection receipt. If its clipboard owner disappears,
release returns `restoration_state=unknown` with a reason and leaves the selection
unchanged. Normal clipboard availability is reported separately.

Universal macOS release binaries target macOS 14.4 or later. X11 capture requires
XComposite and fails explicitly when it cannot capture the selected window.
Wayland capture reports its authorized display source and geometry; portal
display authorization does not establish an exact-window capture capability.
Linux recording requires the reported GStreamer plugins and a Pulse-compatible
audio service; device enumeration alone does not establish recording permission.

The macOS Locked Use authorization plugin, installer, guardian, and run broker
are included in the build/signing chain. Availability is determined from current
OS permissions, matching signatures, installed configuration and the system
authorization rule. The feature uses a full-screen cover with temporary session
unlock and relocks on completion or revocation. It requires explicit per-run
authorization; enabling the setting alone creates no lease. Current implementation
and validation limits are documented in [Persistent Computer Use](computer-use-repl.md).

Google Calendar/People and Microsoft Graph adapters run under the existing MCP
supervisor and application encrypted vault. Native Calendar/Contacts writes,
message sending, real microphone/system recording, and external OAuth writes
were not exercised against personal accounts. They require the dedicated test
accounts/recipient and relevant native permissions described in the plan.

## Running validation

Launch the Electron client from the repository root:

```sh
make -C agi-stack run-desktop
```

Use direct-child temporary QA profile/workspace directories. An existing visual
Provider can be reused in its owning application profile without exporting its
key. Restore the selected workspace and temporary plugin state after acceptance.

Focused checks include:

```sh
cargo test --manifest-path agi-stack/Cargo.toml -p agistack-adapters-cua
cargo test --manifest-path agi-stack/Cargo.toml -p memstack-cua-cloud-connectors
pnpm --dir agi-stack/apps/desktop test:cua-helper
pnpm --dir agi-stack/apps/desktop test:cua-packaging
uv run pytest src/tests/integration/agent/test_native_computer_bridge.py \
  src/tests/integration/agent/test_native_computer_claims.py \
  src/tests/integration/agent/test_native_computer_websocket.py \
  src/tests/integration/agent/test_native_computer_human_resume.py \
  src/tests/unit/infrastructure/agent/test_native_bridge_validation.py \
  src/tests/unit/infrastructure/agent/test_native_computer_use.py \
  src/tests/unit/infrastructure/agent/test_native_permission.py \
  src/tests/unit/infrastructure/agent/test_native_connector_effects.py
```

The native macOS fixture explicitly opts into input in its own disposable app:

```sh
python3 agi-stack/apps/desktop/cua-helper/tests/native_fixture_test.py \
  --allow-own-fixture-input
```

The focused Python bridge suite passed 124 tests with 85.75% coverage of the new
bridge/proxy/claim/handler code. Relevant pre-existing authorization/factory tests
also pass. The sidecar Computer Use suite passed 37 tests, including a real Core
child-run native consent suspension and resumption; six Core HITL tests and eight
Rust server device-bridge tests pass. Linux helper unit tests passed 35 cases,
shared macOS/mock tests passed 21, and Windows GNU builds and test executables
link successfully. The Python wheel includes the runtime skill resource.
Universal signed macOS component packaging checks passed four cases, including
the signed accessory app bundle and rejection of modified bundle metadata.
Renderer checks include a real Chromium opaque-iframe
image load/disposal test with the actual inherited desktop CSP. The result
inspector forwards the same scoped Computer Use presentation as the timeline;
46 focused renderer/bridge/inspector/activity checks and TypeScript compilation
pass, including multiple Windows/Linux tray targets, authorized thumbnails,
reordered image callbacks and stale-generation cleanup.
Actual Electron displays the owned screenshot, canonical application identity and
observation text after the model run. The completed run releases its native
control state. Synchronous authority failure recovery is also covered.
The 2026-10-14 presentation follow-up also passes the 37-test sidecar suite,
including positive pause/resume authorization and owner isolation, 15 common
adapter unit tests and 18 IPC contracts. The separate desktop binary test is
ignored and is not counted as passing. Universal Swift compilation, structural
checks, five live pipe-protocol cases and signature validation pass. A read-only
native AX probe confirms the helper's
`AXExtrasMenuBar` item labeled `Memstack Computer Use` and actual pause/stop
menu entries. Native icon delivery and pause/resume observation invalidation
were exercised against a disposable app. The later complete input fixture did
not finish successfully and is not counted as a passing current acceptance.
The 2026-10-14 Electron UI acceptance was interrupted by a locked Mac. After the
user manually unlocked it, the 2026-10-15 canonical Electron launch reused its
existing MiniMax-M3 configuration and observed only the disposable fixture.
Its application icon and the real `Computer Use Fixture 1` screenshot appeared
in the activity card. Physical clicks changed the card from ready to paused and
back to ready. Stop removed the activity card and both owned native helper and
input watchdog processes exited. The initial resume then failed to observe the
same window because pause cleared the native window registry; the repair keeps
window identities across pause, revalidates them against fresh AX enumeration,
and still discards every old observation and input/resource lease. Structural
and live pipe-protocol checks pass (four protocol cases pass; the locked-desktop
case is skipped while unlocked). No unlock or authorization-database change was
attempted.

The subsequent V12 run displayed the fixture's real blue application icon and
five fresh screenshots in the readable dark activity card. A completed parent
run correctly blocked resume with `parent_run_not_running`. After the user
opened the menu-bar item, the native accessibility tree exposed the preview
image, its timestamp, the target window title, blocked resume and enabled stop.
The automation provider could not capture this windowless accessory application's
menu pixels; those pixels and physical menu-button activation are not counted as
accepted. The helper now ships as `Memstack Computer Use.app` with bundle identity
`ai.agistack.desktop.cua-helper`, rather than an unbundled executable.

V13 exposed a separate history-refresh issue: returning focus cleared existing
messages, temporarily hiding the approval controls. Same-conversation refreshes
now retain their content; first loads, conversation changes and scope changes
retain isolation. Four targeted regression cases cover retention, errors and
stale responses; the related 32-test set and TypeScript check pass. V13's later
authority/loading delay was not proved to be a native IPC deadlock: helper and
sidecar sampling showed idle threads, and the real Stop button immediately
removed the activity card and terminated both owned helper processes. The old
V5 waiting-for-approval test was cancelled through the conversation's official
Stop action, and the UI displayed `Cancelled`.

After a second canonical launch, V15 obtained the real fixture preview and
application icon. While the model was still running, physical UI actions changed
Ready to Paused, exposed Resume, and returned to Ready. The tool group advanced
from three successful steps before the pause to thirteen after resume: one window
enumeration and twelve sequential observations. The window identity stayed
`13794:61E81C32-1F14-43F1-8BFD-91BFBD4FDEDC`; the old `window_not_found` failure did
not recur. The fixture preview showed no held mouse button or Shift key. The
first failed tool result was the expected request for application authorization,
which was approved only for this disposable fixture and session. During this run,
an off-target automation click left approval pending; clicking the actual visible
button at the screenshot's original pixel coordinates continued the run. Pending
UI alone is therefore not evidence of an authorization or native deadlock.

V15's final Stop removed the activity card and terminated the owned helper and
input watchdog while Electron and its sidecar remained running. The result
inspector still rendered the retained artifact and matching window identity.
A subsequent narrow management fix allows Stop to preempt an ordinary pending
management request and prevents late responses from reviving its state. Deferred
tests cover successful/failed stale replies, polling, owner/scope changes and
owner cleanup; the activity/style suite passes 16 cases and both renderer and
Electron TypeScript checks pass. The final Electron receipt changes were made
after V15 Stop and have automated, rather than another native interactive,
validation.

Cleanup restored the plugin to its initial disabled state, confirmed no remaining
application grants and all microphone/system-audio/Locked Use options off, and
archived the QA workspace through its reversible settings control. Its overview
reported zero running or review-pending sessions. The original `编程测试`
workspace was selected again. Electron and its sidecar were closed normally,
and the disposable fixture process was terminated after exact executable-path
verification. No owned helper or watchdog remained; an unrelated legacy socket
helper was left untouched. Historical artifacts and test records remain available
for review.
A green focused suite does not certify missing OS environments or
external account write operations, and does not establish repository-wide
coverage or an unrelated complete-suite result.

### 2026-10-15 native menu acceptance follow-up

The V18 follow-up in the V17 conversation completed real menu-bar acceptance after
the final canonical `make -C agi-stack run-desktop` launch. The independent
[native menu driver](../../agi-stack/apps/desktop/cua-helper/tests/native_menu_driver.md)
captured the actual status icon and layer-101 menu pixels. The menu showed the
fixture's blue application icon, the real `Computer Use Fixture 1` preview and a
readable header. This completes the menu-pixel and native menu-control checks
left open in V12 above. An earlier status-item AXPress returned `-25204` after
opening the menu; fresh inspection confirmed it was open, and the action was
not replayed.

Actual menu Pause produced a paused screenshot with enabled Resume; actual Resume
returned the menu to idle. The authorized preview timestamp advanced from
`15:40:21` to `15:41:16`. The first and last result renderers both retained window
identity `2056:09A1B857-F747-4CB3-A26B-09F140F7EA0F`. An observation attempted while
paused reported `cua_user_paused`; the last tool group contained 14 steps,
including successful observations after resume. Actual menu Stop removed the
activity card and terminated helper PID 803 and watchdog PID 862 while Electron
PID 98728 and sidecar PID 98742 remained running.

This lifecycle run used the existing `MiniMax-M2.7-highspeed` configuration, then
restored MiniMax-M3. The earlier model visual-reasoning evidence remains separate.
Repairs cover the native header icon, normalized and bound target identity,
target-bound previews, persistent menu items, and terminal Stop handling.
Signed component build and Swift structural checks pass; the live protocol suite
passes four cases and skips the locked-desktop case. All five native menu driver
identity tests pass without accessing UI. These checks do not expand the platform
or input-fixture acceptance scope recorded above.

Cleanup has confirmed the plugin is installed but disabled, application grants
are empty, microphone/system-audio/Locked Use are off, the QA workspace is
archived with zero running or review-pending sessions, and `编程测试` is selected.
Electron and its sidecar exited normally. The disposable fixture was terminated
after exact executable-path verification; no owned helper or watchdog remained.
The temporary driver and fixture directories were removed after preserving the
menu screenshots. The unrelated legacy socket helper, historical artifacts and
test records were left intact. At this point workspace selection lasted only for
the running client, and startup could select the first, archived workspace. No
database or unrelated workspace was changed to work around that behavior. The
following navigation fix closes this issue.

### 2026-10-15 workspace selection and restart follow-up

The desktop now saves the selected workspace in a versioned preference scoped by
runtime mode, backend, authenticated user, tenant and project. Local mode uses a
stable backend identity across sidecar port changes. Only the workspace ID is
stored; credentials and runtime configuration are excluded. Startup restores the
preference after loading the authoritative workspace roster. Archived or missing
choices fall back to the first non-archived workspace, or no workspace when none
is eligible. Deletion uses the same eligibility check. Explicitly opening an
archived workspace for history remains available and does not overwrite a valid
active preference.

Authentication hydration passes the verified user ID into runtime refresh rather
than waiting for a React state update. Auth revision, context revision, scope epoch
and request generation checks prevent stale refreshes from selecting or persisting
a workspace for a superseded context.

Renderer TypeScript and test compilation pass. The focused preference, workspace
tree, lifecycle, new-thread, auth-context and login suites pass 109 tests with no
skips. Coverage across the three workspace model modules is 98.73% lines, 94.66%
branches and 98.68% functions; the new preference module is 100% in all three
metrics. These figures do not describe repository-wide or App component coverage.

Real macOS acceptance used three canonical `make -C agi-stack run-desktop`
launches and two complete normal-quit/restart cycles:

1. Initial startup skipped the archived QA workspace. Through its real settings
   UI, the dedicated `Computer Use Visual QA 20261014` workspace was temporarily
   unarchived. Selecting the non-first `编程测试` workspace and quitting normally
   preserved that selection on the next launch, while the QA workspace remained
   active and first in the list. The rendered window and accessibility tree both
   showed the restored workspace.
2. The QA workspace was then selected and archived through its settings UI before
   quitting. The next launch rejected that now-archived saved selection and opened
   `编程测试` (`78eb7080-46e7-4bd7-9132-862508fb795b`). Reopening QA settings
   confirmed the archive switch remained on and there were zero running or
   review-pending sessions.

Cleanup selected `编程测试` again and verified the Computer Use plugin remained
installed but disabled, with no application grants and microphone, system audio
and Locked Use all off. No new session or agent run was started. Electron and its
sidecar exited normally after each cycle, including final PIDs 15980 and 15988;
their children and the owned development watcher also exited. The unrelated legacy
socket helper, historical QA artifacts, conversations and other workspace data
were preserved. This restart acceptance covers macOS local mode; Windows, Linux
and native cloud-account switching were not exercised in this follow-up.

### 2026-10-15 cloud Resume repair and native acceptance

Cloud Resume now revalidates the retained invocation through authenticated HTTP
before releasing a paused native session. The sidecar matches every returned
owner, device, conversation, run, engine-session and revision field, rejects an
expired response, and checks local plugin and connection authority again after
the request. Completed invocation results remain cached independently of a
cancellation marker, so cancellation cannot make a completed request resumable.
Python workspace validation preserves the initial workspace ID before awaiting
other authority checks; an ORM refresh cannot conceal a workspace change by
updating the same in-memory conversation object.

Native reset, resume and final teardown share a resource lock. Stop marks the
session terminal and interrupts native input before waiting for final cleanup;
authority and deadline checks after native IPC prevent a delayed recovery from
recreating stopped resources. The native status listener continues receiving
Stop while cloud Resume waits for HTTP. Presentation refreshes cannot restart an
expired or stopped helper session. Resume invalidates observations and does not
restart audio or replay the previous tool action.

The focused Rust server Computer Use suite passes 14 tests, including six fresh
Resume authority tests. The sidecar Computer Use suite passes 51 tests, including
deterministic private-IPC checks that hold reset, pause and resume at native
boundaries while Stop runs, and that hold the cloud response while a native-menu
Stop arrives. Explicit Stop also persists a denial for the current owner/device/run
and fences new claims, including a new request, engine session or connection for
that same run. A failed persistence write retains the in-memory fence. Different
owners and fresh runs remain independent. Formatting and diff checks pass. These
tests use authenticated protocol fixtures without operating-system input; the
native client results are recorded separately below.

#### Python production wiring and request latency

The production V2 agent route definitions now register device status, claim and
Resume authority endpoints. A real production route-table integration test covers
status, claim, result and Resume; testing the legacy aggregate router alone had
missed the registration gap. The focused Python Resume and route tests pass
38 cases, including cancellation during validation, an ORM identity-map refresh
that changes the workspace, terminal parent runs and disconnected devices. Test
Redis records use disposable UUID-prefixed namespaces and remove only their own
records.

The combined production base bundle now includes the existing
`memstack-computer-use` manifest referenced by its target profile. The supported
baseline upgrade consequently composes the full first-party bundle without
adding a separate bundle or weakening artifact validation. The production and
maintenance tests pass 36 cases. Two regression cases upgrade legacy tenant and
project profiles while retaining a verified third-party bundle, operator
replacements and disabled entries. The new native factory is present with its
default execution setting disabled. Existing protocol generation checks pass.

Real client requests exposed repeated synchronous archive verification and
profile compilation on every feature admission. The scoped bundle loader now
reuses verification of its deployment-owned immutable built-in archive and
returns independent manifest mappings. Third-party bundles still reload current
installation, revocation, permission and artifact authority on every call.
`src/infrastructure/plugins/v2/profile_composition_cache.py` provides a bounded
runtime-owned compilation cache; application services load current authority
before consulting it. Cache hits require complete input equality as well as
scope and exact references. Results are copied, and runtime shutdown clears the
cache. This avoids sharing mutable configuration or caching authorization.

The focused cache, instance-management, loader and startup suite passes 24 tests,
with 100% coverage of the compilation cache and 97.73% of the scoped loader
(98.70% combined). It exercises changed revisions, revocation after a cache hit,
altered inputs retaining an old digest, mutation of returned mappings, scope
isolation and bounded eviction. An offline benchmark of the same production
archive and profile, excluding database and network time, took 1.816 seconds for
five uncached iterations and 0.265 seconds for five warm cached iterations. These
measurements describe the pure validation/compilation path, not an end-to-end
latency guarantee.

```bash
uv run pytest \
  src/tests/unit/infrastructure/plugins/v2/test_profile_composition_cache_v2.py \
  src/tests/unit/application/services/test_builtin_bundle_loading_cache_v2.py \
  src/tests/unit/application/services/test_plugin_instance_service_v2.py \
  src/tests/unit/application/services/test_scoped_installed_bundle_loader_v2.py \
  src/tests/unit/infrastructure/adapters/primary/web/startup/test_scoped_profile_runtime_v2.py \
  -q --cov=src.infrastructure.plugins.v2.profile_composition_cache \
  --cov=src.application.services.scoped_installed_bundle_loader_v2 --cov-report=term-missing
```

Cancellation settlement now closes unfinished tool records for the exact
cancelled run message and tenant/project/conversation scope, while preserving
completed results and adjacent runs. The existing authenticated cancellation
endpoint can repair an interrupted terminal projection when the same owner
retries its original revision receipt. It does not dispatch another action or
replay a device request. The focused persistence and cancellation API suite
passes 22 tests, with 100% coverage of the new settlement helper; these tests also
cover scope mismatches, nonterminal authority and idempotent repair.

Fresh native observations explicitly declare `repeatable_observation` in static
tool metadata. The converter, processor and optional tool pipeline preserve this
boolean; both execution paths allow repeated samples of the same window. Each
sample still obtains current authority and dispatches separately. This fixes a
real client stall where the fourth identical observation waited on a hidden
generic repeat approval before reaching the device broker. Mutation tools and
consecutive-error protection retain their existing checks. The focused Python
suite passes 79 tests, including 15 new cases and five identical observations
through each real factory/converter/execution path.

Native application consent remains manual under both relaxed and full generic
approval presets. The native binding and computer-application decision target
exclude these requests from automatic approvals. Grants immediately remove the
matching pending row from the native presentation without consuming a one-use
grant early. Transcript image cards now use the existing authenticated artifact
image loader; the Electron content-security policy remains unchanged. The six
focused desktop suites pass 77 tests, and TypeScript compilation passes.

Validated session projections now update both the open conversation and the
workspace conversation cache. Tenant, project, workspace and conversation must
match before a projected run is applied. This prevents a terminal conversation
from remaining counted as running until a client restart. A run's permission
revision is distinct from its lifecycle timestamps: queued, running and failed
can share one revision, so equal-revision updates for the same run are ordered
by their authoritative update time while older projections remain rejected.
The focused session, workspace-overview and workspace-tree suites pass 82
tests, including queued-to-terminal updates with an unchanged permission revision.

#### Real Electron results

The client was launched from the repository root using
`make -C agi-stack run-desktop`. It reused the existing encrypted cloud Provider
configuration; no Provider credential was exported or replaced. Testing was
limited to the disposable `Computer Use Fixture` application and the dedicated
`Cloud Computer Use QA 20261015` workspace.

Run `ebc5501e-3318-5389-b636-95e46f9e535a` required separate manual observation
and control grants, each limited to that run. The model activated Fixture 1,
received a real 1120-by-864 screenshot and performed exactly one successful
click at screenshot coordinates (560, 498). The subsequent screenshot and AX
state both showed `clicked:blue:circle`. The real client displayed the fixture
application icon, the matching window title and preview, and authenticated
transcript images. Earlier focus/stale-observation failures and a missed click
were not counted as visual success.

The final observation-only run `aa5487b4-443d-5378-858c-4012d81c1255` again
required manual native consent despite the relaxed generic read preset. The
broker recorded 13 successful observations with distinct snapshot IDs: eight
before Pause and five after Resume. An observation attempted while paused
returned `cua_user_paused` without an image. The actual Resume button obtained a
fresh HTTP authority response (200), followed by a new screenshot with snapshot
`EA9CAB67-5AB2-46D4-A8FF-0B2D66800BB1`. No input action was requested in this run.

Clicking Stop closed the native control panel. A later request in the same run
returned `cua_permission_denied_run` without a screenshot and could not recreate
the native session. All 17 broker requests became cancellation tombstones while
completed results remained available. The parent finished with a failed summary
because the deliberate Pause and Stop rejections were recorded as two failed
tools; there were no unfinished tool records. Counts here come from broker
records, not the model's inconsistent final observation count. The workspace
overview showed zero running and zero review items after returning from the
conversation. A fresh authoritative read after the lifecycle timestamp fix also
updated both the sidebar and recent-conversation row from queued to failed,
matching the actual terminal run. That display check temporarily unarchived the
same test workspace because the existing archived-workspace boundary returns
404 for the run-control projection; it was archived again without another run.

#### Cleanup and restored state

The test conversation's generic approval preset was restored to default. The
cloud test workspace was archived, and the prior cloud selection
`权限边界验收 20260914` was restored before signing out of the test cloud login.
Computer Use remained installed but disabled in that cloud project, with no
application grants and microphone, system audio and Locked Use all off.

Returning through the real local-login UI automatically selected the original
`编程测试` workspace (`78eb7080-46e7-4bd7-9132-862508fb795b`), not the archived
Computer Use test workspace. Local Computer Use was independently verified as
installed but disabled, with no grants and all three additional capabilities
off. Existing Provider credentials and configuration were unchanged.

Electron exited normally together with its sidecar, workspace-core child and
helper processes. The owned fixture and local Python development backend also
exited; port 8000 had no remaining listener. Only the two task-owned disposable
fixture/backend directories were removed. Test conversations and artifact
history, unrelated worktree changes, existing infrastructure services and the
preexisting legacy helper were preserved. No Windows, X11, Wayland, Locked Use
or remote production-server acceptance is inferred from this macOS cloud test.

### User control is distinct from tool failure (2026-10-16)

Native Pause and Stop now have a typed control outcome, separate from the error
channel. The authenticated native result must match its declared outcome and
contain neither an error nor media. Arbitrary connector output, result text or
renderer messages cannot grant that status. Interrupted calls are recorded as
cancelled and displayed as paused or stopped; they are not counted as failed or
as executed actions. Permission refusal, platform failure and policy rejection
retain their error status.

A paused cloud call waits at the execution boundary for a successful native
Resume or Stop notification. The notification is bound to the device connection,
run, native session, request and pause generation. Retained native notifications
and a durable server stream cover a notification arriving before its waiter;
an old generation cannot resume a newer pause. Resume continues with a fresh
model turn rather than replaying the interrupted call.

Stopping computer use does not imply the overall objective was achieved. Only
a trusted Stop enables the structured goal judge's `control_handoff` verdict.
It can end the turn normally when remaining work requires stopped desktop
interaction, while leaving the goal incomplete. Other authorized work may
continue. Failed tasks and unverifiable task authority still fail closed; a
handoff and goal-achieved verdict cannot both be true. The judgment is audited
with its input, typed output, rationale and latency, and control evidence is
reset for each new run.

#### Real macOS cloud-client acceptance

The native client was launched from the repository root with
`make -C agi-stack run-desktop`, using the existing encrypted MiniMax-M3 Provider
configuration and the local development cloud backend. Conversation
`70df02c9-28b1-5921-a602-30a211a2aa6d`, execution
`682d295d-d003-4450-98e5-a4acb23d8af6`, exercised only the disposable
`ai.memstack.cua.fixture` application's first window. Its observation permission
was granted through the actual client for the current session. The app icon and
window preview were visible, and committed model messages contained real
`artifact_image` content blocks.

The actual Pause button produced a neutral `电脑操作已暂停` timeline group.
The authenticated result was `user_paused`, with no error or media; the stored
tool status was cancelled. During a measured 38-second paused interval, the
native request count remained eight and the parent remained running. Clicking
Resume delivered the matching pause-generation notification. Four successful
screenshots preceded Pause and ten new screenshots followed Resume. No old
request was replayed. A stale window handle returned a genuine
`window_not_found` error; the agent enumerated the window again and continued
with a new handle.

The actual Stop button closed the control panel and produced the neutral
`已停止` group. The run ended with `user_control:stopped` and a normal complete
event, reaching `ready_review` rather than failed. Its durable execution summary
contains `completion_reason=user_control_handoff`, `goal_achieved=false`, and
`control_outcome=user_stopped`. All 21 native requests became cancellation
tombstones; there were 14 successful screenshot artifacts and no native
execution or new screenshot after Stop. These counts come from broker records:
the model's final prose
incorrectly counted a control response as a fifteenth successful observation.

The run also contained 19 genuine rejected `todowrite` calls: the model omitted
the top-level task ID or split update fields into multiple items, so read-only
run authorization correctly rejected them. They remain failed, as does the
stale-window error; the seven task records remain pending. User control does
not turn those errors into success. The permissive existing task-tool schema
and the model's inaccurate explanation of these rejections are separate known
limitations. Reloading the actual client and reopening the conversation
preserved `ready_review`, the neutral Pause/Stop groups, and the real error
groups.

Focused regressions passed: 59 goal/completion tests (84.28% combined coverage
for goal evaluation/judgment), 58 native sidecar control tests, 17 server bridge
tests, 14 core tests, three local wait tests, and 88 desktop tests. The Python
control suite also passed, with 91.06% coverage for its new control helper.
These are scoped test results, not a claim that the whole repository or other
operating systems were validated.

#### Cleanup after this acceptance

The conversation approval preset was restored to default. Cloud Computer Use
was restored to installed-but-disabled, with no application grants; microphone,
system audio and Locked Use stayed off. The test workspace was archived through
the client, and its canonical persisted `is_archived=true` was verified. The
prior cloud workspace `权限边界验收 20260914` was selected before signing out.
Returning through the local login restored `编程测试`; local Computer Use also
remained disabled with no grants and all three additional capabilities off.
Existing Provider configuration and encrypted credentials were not changed.

Electron exited normally and its process group, including the sidecar and
children, became empty. The fixture and owned local development backend were
terminated by their verified process identity. Both task-owned disposable
directories were removed after verifying that no process still used them.
Conversation/artifact history, unrelated worktree changes, infrastructure
services, and the preexisting legacy helper were preserved. This acceptance
does not cover Windows, X11, Wayland, Locked Use, or a remote production server.

### Task argument validation and Stop cleanup (2026-10-16)

The task-write contract now declares the actual update shape to the model:
top-level `todo_id` and exactly one patch object in `todos`. It rejects split
patch objects, missing identities, unsupported fields such as `$text`, and
invalid statuses. The direct tool entry validates the same schema and rejects
conflicting nested IDs without guessing the intended task. Error responses
include structured argument paths and correction guidance.

The execution pipeline validates declared parameters before permission
resolution and validates again after hooks. This prevents malformed updates
from being misreported as authorization failures. Valid progress updates still
require normal conversation scope and permission checks; structural task edits
continue to require write authorization. Stop guidance explicitly preserves
authorized task-progress bookkeeping, asks the agent to select statuses from
actual outcomes, and requires reading back the ledger before claiming success.
The client displays persisted cancelled state rather than manufacturing it
from a Stop action or a failed update.

Focused tests passed: 102 task-contract/permission/persistence tests with 100%
coverage of `todo_contract.py`; 60 pipeline/processor/provider feedback tests
with 96.41% pipeline coverage; 28 native control/handoff tests; and 23 desktop
model/component tests with a fresh TypeScript compile. These counts describe
the individual focused suites and are not a unique repository-wide test total.
Regressions include an approved read-only run, SQLite task persistence without
changing its approved plan snapshot, malformed hook-modified arguments, provider
schema forwarding, genuine error preservation, and cancelled task rendering.

#### Actual Electron and model acceptance

Launched from the repository root with `make -C agi-stack run-desktop`, using
the existing encrypted desktop profile and existing MiniMax-M3 Provider. The
cloud-mode client used the owned local Python development backend and a fresh
ad hoc signed fixture process (`ai.memstack.cua.fixture`, pid 91777). Only its
`Computer Use Fixture 1` window was authorized for session-scoped observation.
No click, input, audio, connector, or project-file operation was requested.

Conversation `790f8fb8-9552-55b1-9ad9-4624cded8a75` generated a three-step plan;
the actual client approved version 1 with `read_only`. Execution run
`330c0715-cee5-4cd3-996a-e5bd88265bcb` performed three successful native screenshot
observations. The client showed the target window preview, first task completed,
and observation task in progress before the actual Stop button was clicked.

All six model-generated `todowrite` calls had valid arguments and succeeded,
including the updates after Stop. The agent read back the task ledger; durable
task states were `completed`, `cancelled`, `completed`. There were zero invalid
argument, permission, or tool failures. The stopped native request returned
`user_stopped`, `is_error=false`, and no media. The run reached `ready_review`
with `completion_reason=user_control_handoff`, `goal_achieved=false`, and
`control_outcome=user_stopped`. Seven native requests became cancellation
tombstones; no new native execution or screenshot followed Stop.

Reloading Electron and reopening the conversation preserved the neutral
`已停止` group, `已完成 2/3`, the cancelled observation task, and `ready_review`.
The approved plan snapshot remained version 1; only task progress changed.
This closes the malformed-todo limitation recorded in the preceding acceptance
section for this tested Provider and flow. It does not guarantee that a model
will never generate malformed arguments; such arguments now receive actionable
validation errors without mutating tasks or bypassing authorization.

#### Cleanup after the task-argument acceptance

Cloud Computer Use was restored to installed-but-disabled with no application
grants; microphone, system audio, and Locked Use remained off. The conversation
approval preset remained default. The test workspace was archived through its
actual settings dialog and canonical persistence confirmed `is_archived=true`.
The prior cloud workspace `权限边界验收 20260914` was selected before logout;
local login restored `编程测试` and confirmed that local Computer Use was also
disabled, without grants or additional capabilities enabled.

Electron exited normally through Quit, and its sidecar process group became
empty. The verified fixture and owned development backend were terminated;
both owned temporary directories were removed after confirming no process
used them. Provider configuration, credentials, conversation/artifact history,
unrelated worktree changes, infrastructure services, and the preexisting helper
were preserved. Windows, X11, Wayland, Locked Use, and a remote production
server were not revalidated by this task-focused acceptance.

### Pause, resume, and task progress follow-up (2026-10-16)

An actual cloud-mode Electron run exposed a failure during prolonged Pause:
the device connection closed, and the model subsequently described the lost
connection as user Stop and cancelled the observation task. The run had no
confirmed Resume or Stop notification. That run is retained as a pre-fix
failure, not a successful lifecycle acceptance.

The native agent WebSocket now owns its heartbeat and response deadline in
Electron main. It sends a heartbeat every 20 seconds and only valid inbound
frames renew the 60-second response deadline. The renderer no longer duplicates
those timers for the native transport; raw WebSocket behavior is unchanged.
Owner cancellation and transport finalization clear the timer, and late frames
cannot revive the connection. The original disconnect lacked a close code, so
this fixes a demonstrated lifecycle risk without claiming it was the only
possible cause of that particular disconnect.

A failed trusted Pause wait now produces `NativeControlWaitError` and an explicit
error observation, then terminates the run before another model turn or goal
evaluation. It does not synthesize user Stop or mutate tasks. Persistence can
upgrade a previously recorded, exact typed Pause result to a later real failure
only for the same conversation, message, call, and tool. Atomic guards prevent
cross-scope changes and late success or Pause events from hiding that failure.

The focused Python regressions cover direct and pipeline execution, concurrent
calls, task-ledger preservation, failed waits, and event projection: 99 tests
passed, with 93.58% coverage of the native-control wait and tool-event projection
modules. Client broker, React hook, policy, native bridge, and lifecycle
regressions passed 70 tests, including four minutes with an inactive renderer,
a genuinely unresponsive server, and cancellation followed by a late response.
Both desktop TypeScript configurations, focused Python typing and lint, and
`git diff --check` passed.

#### Actual Pause, Resume, Stop, and task-ledger acceptance

After restarting the owned Python backend and launching Electron again from the
repository root with `make -C agi-stack run-desktop`, conversation
`b297eb33-1ae7-5fdc-91db-249e26e88fa7` used the existing encrypted profile and
MiniMax-M3 Provider. The actual client approved a three-step, read-only plan.
Execution run `544b8842-a3c8-42a8-8ed9-3ceabcde0809` observed only the owned
`ai.memstack.cua.fixture` process, pid 63279. Session-scoped application consent,
the program icon, and the `Computer Use Fixture 1` preview were visible in the
native client.

The actual Pause button changed the control panel to `已暂停` and exposed Resume.
Between 15:30:23.800 and 15:32:08.832 local time, a 105-second interval, all nine
native request records and five successful screenshots remained unchanged.
Tasks stayed `completed`, `in_progress`, `pending`; no task was cancelled and
the paused request retained its original control generation without a Resume or
Stop notification. The native screenshot also showed the paused preview and
the task panel at `已完成 1/3` with one task in progress.

Clicking Resume produced an accepted notification for that exact generation.
The old request was not replayed. A new call using the old window handle received
`window_not_found`; the agent enumerated the application and window again and
then produced three new successful screenshots under new request and snapshot
identities. That real, recovered error remains in the tool ledger. This is not
an assertion of an error-free run or acceptance of reusing old window handles.

Clicking Stop returned trusted `user_stopped`, `is_error=false`, without media.
The agent's eight progress updates and two task readbacks all succeeded with
valid arguments. The final ledger was `completed`, `cancelled`, `completed`.
At 15:34:21 the run reached `ready_review`, revision 2, with
`completion_reason=user_control_handoff`, `goal_achieved=false`, and
`control_outcome=user_stopped`. The client displayed `可以开始审查`, `已完成 2/3`,
and the cancelled observation task. Reopening the conversation preserved that
state and the neutral `已停止` tool group. There were sixteen native request
records and eight successful screenshot artifacts in total; no new native
execution followed Stop and all requests became terminal tombstones. These
counts come from the stored requests and artifacts, not the model's prose
summary, which overstated its observation count.

#### Cleanup after Pause and Resume acceptance

The cloud plugin was restored to installed-but-disabled with no application
grants. Microphone, system audio, and Locked Use stayed off. The actual workspace
settings dialog archived the test workspace; canonical persistence confirmed
`is_archived=true`. The previous cloud workspace `权限边界验收 20260914` was
selected before logout. Local login restored `编程测试`, and its plugin settings
confirmed disabled Computer Use, no grants, and all three additional
capabilities off.

Settings were closed and Electron exited through its native Quit menu. Its
owned process group was empty. Only the verified fixture and owned development
backend were terminated; both owned temporary directories were removed after
checking their process groups and open files. The preexisting helper, other
infrastructure, Provider/vault data, conversation/artifact history, and unrelated
worktree changes were preserved. This follow-up validates the macOS client and
local development cloud bridge; Windows, X11, Wayland, Locked Use, and a remote
production server were not revalidated.

### Recording stability follow-up (2026-10-19)

Independent recording Stop/export retry, durable owner-bound receipts, restricted
cloud cleanup, scoped client controls, and fresh-window Resume guidance are
documented in [Computer Use stability follow-up — 2026-10-19](computer-use-stability-2026-10-19.md).
That document lists each automated suite separately and records the crash/recovery
limits. Its Native acceptance section records actual macOS local/cloud system
recording Stop, saved-audio playback, long-pause recovery without automatic
re-recording, failure reporting, and scoped cleanup. It does not claim microphone,
Locked Use, Windows, or Linux native acceptance.
