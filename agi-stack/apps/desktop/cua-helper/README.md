# Desktop Computer Use helper

The macOS helper implements IPC 3 over inherited stdin/stdout pipes. The Rust
sidecar owns its process and injects the user, tenant, project, conversation, run,
device, and session context. stderr contains diagnostics; stdout contains framed JSON-RPC
only. No Unix socket, argv, environment variable, or credential file carries the
bootstrap secret.

## Build and checks

Run the native client with make -C agi-stack run-desktop. ./build.sh compiles
the helper plus the separate lock continuity guardian, authorization plugin, and
installer, packaged as bin/Memstack Computer Use.app with the stable bundle ID
ai.agistack.desktop.cua-helper. Its accessory application owns the native menu
bar item. The sidecar directly spawns Contents/MacOS/cua-helper with private
pipes; LaunchServices or a public control socket is not used for requests.
Builds do not replace a running sidecar's helper. The canonical Make target
explicitly stages the application beside the sidecar before launching it.
Set MEMSTACK_CUA_UNIVERSAL=1 for universal macOS release binaries.
MEMSTACK_CUA_CODESIGN_IDENTITY selects a stable development signing identity;
local builds use explicit ad-hoc identifiers.

Run ./test.sh for Swift structural checks and real helper protocol tests. Those
tests do not synthesize desktop input, record audio, send messages, install
authorization components, or lock/unlock the machine.

## Protocol and ownership

Frames have a four-byte little-endian length and an 8 MiB limit. The first request
must be initialize, id 0, with client_api_version: MemstackComputerUseIPC-3,
nonce, and secret. The response echoes the nonce and includes a lowercase hex
HMAC-SHA256 proof, keyed by secret UTF-8 bytes over nonce UTF-8 bytes.

begin_session binds nonempty user_id, tenant_id, project_id, conversation_id,
run_id, device_id, and the trusted input_mode. It returns session_id, private
artifact_root, input_mode, and input_generation. Subsequent operations require
that live session, unchanged owner fields, and the current input binding.
The host adds these fields; ordinary model action arguments cannot choose a mode
or a process. stop_session is consumed immediately by
the reader, cancelling long input while native operations remain serialized.
end_session releases input/audio/clipboard resources and temporary artifacts.
reset_session recovers ordinary cancellation and clears observations. Terminal
Stop and user Pause reject reset; a stopped run needs a new authorized session.

resolve_app returns canonical bundle identity and a stable code identity digest.
The caller freezes the resolved PID and expected digest before authorization.
list_windows and get_app_state return explicit window/snapshot identities.
Opaque window IDs follow the verified process birth and native WindowServer ID.
If AX omits a previously observed window on another Space, the helper retains it
only after rechecking its live AX role/PID/window ID and WindowServer owner and
bounds. Titles and geometry never establish window identity.
Every input requires the current snapshot, input generation, expected code identity,
and a unique request ID. Foreground input additionally requires the observed
application's focused window. Observations become
stale after input. Forbidden bundle IDs are checked after native resolution.

Screenshot results use ScreenCaptureKit and return private file URLs, actual
dimensions, MIME type, and logical window bounds. The sidecar must copy completed
media into its persistent artifact store before ending the helper session.

## Native extensions

New sessions request background input by default. Users explicitly select
foreground mode in desktop Computer Use settings. Background input binds the
process birth identity and native window, keeps separate held-input state, and
posts events to that process. Its private window-coordinate and synthetic-focus
operations are isolated in InputRouting.swift and probed at runtime. An unavailable
background capability returns a reason; it never selects global input implicitly.
MEMSTACK_CUA_DISABLE_BACKGROUND_INPUT=1 disables the private background channel.
Secure Event Input blocks background dispatch. Key names identify physical ANSI
key positions; the target's active input source interprets them. Capabilities
report both the keyboard layout and input source. Input-source queries run on the
AppKit main thread, including requests arriving on the IPC queue. type_text
inserts literal Unicode and does not simulate IME composition.
Typing Unicode text, sending key chords, changing AX values, and clipboard paste
remain separate operations.

The background channel does not emulate global pressed-button state. Some
applications, including the tested WebKit and Electron DOM drag targets, therefore
cannot complete a background drag even though they receive events. The focus
guard protects verified notification/keyboard routing; it cannot prevent arbitrary
application-initiated global activation. A target becoming frontmost pauses the
session. Both limitations are declared in background capability metadata.

The initialize option input_telemetry_notifications subscribes to
native_input_telemetry notifications. Each includes owner context, generation,
sequence, target, virtual pointer, and the complete held-key/button state. It never
contains typed text. Delivery means the event was dispatched; a fresh observation
is needed to confirm the application result. Telemetry is coalesced per session
and kept separate from control responses and lifecycle notifications.

The opt-in tests/background_fixture_test.py --allow-own-fixture-input uses two
disposable signed applications and an independent system-input observer. It checks
targeted input, unchanged foreground focus and system cursor, pause/resume, stale
generations, and helper crash recovery. This automated test does not substitute
for simultaneous physical keyboard/trackpad or multi-Space acceptance.

Set `CUA_FIXTURE_CONTENT=webkit` or `CUA_FIXTURE_CONTENT=electron` to exercise the
corresponding receiver, and `CUA_FIXTURE_SCREEN_INDEX=1` for a second display.
The ordinary test requires a completed drag. The explicit
`--expect-global-button-limit` option instead requires the known trusted-event /
zero-DOM-button-state failure and reports a separate compatibility result; it is
not a full drag acceptance result.

`tests/keyboard_input_fixture_test.py --allow-own-fixture-input --case layout`
temporarily selects the installed French layout, verifies physical positions and
literal Unicode, then restores the original source. The `--case ime --human-ime
--ime-source <installed-source-id>` variant waits for real uncommitted text in the
foreground Guard and verifies that background input leaves it intact before the
operator continues and commits it. Instructions appear inside the Guard window.

`tests/native_compatibility_fixture_test.py --allow-own-fixture-input --scenario
space` waits for real Space transitions. `--scenario lock` waits for an operator
to lock and unlock the Mac, then verifies hold release, terminal rejection of the
old session and a fresh session after unlock. These tests never enter credentials
or install the separate Locked Use authorization plugin.

`tests/physical_input_test.py --allow-own-fixture-input` is a separate,
human-assisted one-minute check. It waits for an explicit start and requires the
operator to move a physical mouse, type neutral text, and hold Shift in Foreground
Guard while the helper types in Background Target. It does not synthesize the
operator's input. `--fault-target-exit` on the automated fixture tests cleanup
after the owned target exits instead of killing the helper.

The helper implements click, drag, text input, chords, scroll, AX set-value and
secondary actions, exact UTF-16 text selection, held keys, pointer movement, and
incremental drag. Owned keys/buttons are released on stop and channel loss.
Clipboard handles preserve all readable types/items and restore only content
still owned by the operation.

Audio uses AVAudioEngine for microphones and ScreenCaptureKit for system audio.
All exported recordings use 24 kHz stereo PCM16 WAV. Mixed mode aligns both sources
on their host-clock timeline and publishes one mixed WAV on stop. Original tracks
stay private; if mixing fails, each valid source is normalized and exported as a
partial recording. `max_duration_ms` accepts integers from 100 through 300000;
omission retains the five-minute default. Recording also has a 64 MiB limit.
Artificial PCM tests cover resampling, source offsets, gain, and export fallback.
Active status reports counters; completed files are published on stop.

EventKit and Contacts provide bounded native list/create/update/delete operations.
Updates require an exact id and a supported fields object; deletes require an exact id. Messages uses
only fixed operations declared in the installed Messages.sdef: list accounts,
resolve a participant, and send. User values are Apple Event descriptor
arguments and never executable AppleScript source. Permission requests are
explicit; capability reads do not trigger consent dialogs.

## Lock continuity

Lock continuity is a separately packaged, signed authorization plugin, independent
guardian, administrator installer, and helper broker/AX coordinator. The installer
preserves existing screensaver authorization branches and validates component
signatures. Installation or removal requires native administrator authorization.

The host owns the session/run/generation binding and renews a lease of at most ten
seconds. A dedicated queue prepares all-display coverage before a single short
authorization attempt. The independent guardian and input watchdog validate
process birth identities and the absolute host deadline; ordinary input heartbeat
traffic cannot renew lock continuity. Physical input, timeout, host EOF, or either
supervisor exiting revoke authorization and retain surviving coverage until the
OS reports a locked console. Each authorization rechecks the guardian's live state.

Capability reads check current permissions, matching stable signatures, installed
configuration, and the actual authorization branches. The installer stages a
root-owned rollback transaction; a later administrator operation recovers an
interruption while preserving unrelated authorization branches. Local packaging
honors `MEMSTACK_CUA_CODESIGN_IDENTITY` for stable signatures, while ad-hoc builds
cannot install or enable lock continuity. Release packaging still requires its
configured signing identity and notarization.

Executable tests cover lease expiry, stale identities, frame timeouts, and child
termination at each installation stage using temporary files and a fixture rights
store. Real isolated unlock, coverage, physical-input, and crash acceptance is
still required; these tests never install the system plugin or unlock the Mac.
The opt-in compatibility test observes an operator's real lock/unlock transitions
to verify that ordinary input stops; this does not validate Locked Use.
