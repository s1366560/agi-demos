# Desktop Computer Use helper

The macOS helper implements IPC 2 over inherited stdin/stdout pipes. The Rust
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
must be initialize, id 0, with client_api_version: MemstackComputerUseIPC-2,
nonce, and secret. The response echoes the nonce and includes a lowercase hex
HMAC-SHA256 proof, keyed by secret UTF-8 bytes over nonce UTF-8 bytes.

begin_session binds nonempty user_id, tenant_id, project_id, conversation_id,
run_id, and device_id and returns its session_id and private artifact_root. Other
operations require that live session and unchanged owner fields. stop_session is consumed immediately by
the reader, cancelling long input while native operations remain serialized.
end_session releases input/audio/clipboard resources and temporary artifacts.
reset_session recovers ordinary cancellation and clears observations. Terminal
Stop and user Pause reject reset; a stopped run needs a new authorized session.

resolve_app returns canonical bundle identity and a stable code identity digest.
The caller freezes the resolved PID and expected digest before authorization.
list_windows and get_app_state return explicit window/snapshot identities.
Every input requires the current snapshot, expected code identity, a unique
request ID, and the observed application's focused window. Observations become
stale after input. Forbidden bundle IDs are checked after native resolution.

Screenshot results use ScreenCaptureKit and return private file URLs, actual
dimensions, MIME type, and logical window bounds. The sidecar must copy completed
media into its persistent artifact store before ending the helper session.

## Native extensions

The helper implements click, drag, text input, chords, scroll, AX set-value and
secondary actions, exact UTF-16 text selection, held keys, pointer movement, and
incremental drag. Owned keys/buttons are released on stop and channel loss.
Clipboard handles preserve all readable types/items and restore only content
still owned by the operation.

Audio uses AVAudioEngine for microphones and ScreenCaptureKit for system audio.
Mixed mode converts both sources to a common 48 kHz stereo timeline and publishes
one 16-bit mixed WAV on stop. Original tracks stay private. Recording has a
five-minute/64 MiB limit. Artificial PCM tests cover resampling and source offsets.
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

The implementation covers displays, filters physical versus owned synthesized
input, leases a short authorization attempt, and requests native relock on input,
expiry, or parent channel loss. The ordinary locked_use capability remains
unverified: the isolated native unlock/coverage/input/crash acceptance has not
been run. Local tests never install the plugin or exercise lock/unlock.
