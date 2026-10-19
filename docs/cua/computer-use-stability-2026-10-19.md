# Computer Use stability follow-up — 2026-10-19

This follow-up records the implementation and automated checks for recording
lifecycle, scoped client controls, cloud cleanup, and recovery guidance. It
extends [the implementation document](computer-use-implementation.md). The
automated results below do not establish native application acceptance. The
Native acceptance section separately records actual macOS client observations.

## Runtime and recording lifecycle

Python and Rust resume guidance now requires `computer_list_windows`, a current
`window_id`, and a fresh observation before another desktop action. An interrupted
action may have partial effects; Resume neither replays it automatically nor
restarts audio recording. The MCP connector bridge propagates structured
`is_error` results as `CoreError`, preserving tool failures for the agent.

Local Stop preserves exact tool dispatch routes for terminal control receipts
after removing stopped tools from the model catalog. Calls already planned
through both composite hosts reach `UserStopped` without native execution.
Explicit execution-profile allowlists do not re-advertise these stopped
canonical tools; MCP compatibility aliases retain their existing behavior.
Revoked authority remains a failure and is not converted into user Stop.

Recordings have independent generation IDs and owner-bound receipts. Native stop
requests capture shutdown and closes the WAV writers before mixing or artifact
export. ScreenCaptureKit shutdown completion is not guaranteed after its bounded
wait; repeated stop retains the original terminal reason. Pause, Stop, session
cleanup, revocation, and expiry stop capture without granting permission to start
again. Valid partial audio can be retained with `partial: true` and an error code.
Mixed capture retains valid tracks when another source fails. Duration, byte, or
device-loss termination stops the whole recording group.

The sidecar persists recording receipts in `desktop_cua_recordings_v2`. Export
validates the owned WAV source, copies it to durable artifact storage, and uses
stable artifact IDs for retries. It saves the receipt before sending native
`audio_ack`. Export failure retains the sealed source and exposes
`can_retry_export: true`; retry exports those bytes without reopening capture
devices or obtaining another execution grant. A request for an old recording ID
cannot stop a newer recording generation.

Source I/O distinguishes `ErrorKind::NotFound` as `cua_audio_source_missing` and
sets `can_retry_export: false`. Permission and transient I/O failures retain the
retry path. A retry of an older unavailable-source receipt rechecks the source
and can update this classification without changing its recording identity,
timestamps, completion reason, or historical native receipt. The client explains
that a missing source cannot be saved, rather than reporting a capture failure.

Real macOS Pause acceptance exposed a cleanup error: directory enumeration
returned `/private/var/...` while retained recording URLs used `/var/...`. Raw URL
comparison incorrectly deleted sealed, unacknowledged audio. Cleanup now resolves
symlinks and standardizes both sides. A real-filesystem regression preserves
sealed system audio, mixed audio, and source tracks through both path spellings
and an explicit symlink alias, while removing transient screenshots.

The existing-session IPC path accepts only `audio_status`, `audio_stop`, and
`audio_ack`; it does not spawn a helper or begin a session. Cloud `audio_stop`
alone can use an in-memory cleanup binding established by prior online user and
project validation. That binding includes the owner and a digest of the trusted
credential record and epoch, with revalidation before returning. Changed scope,
owner, device, session, recording ID, credentials, or epoch rejects admission.
If the identity changes after native Stop was dispatched, that cleanup may still
complete; the final identity-ticket check prevents returning the previous owner's
snapshot.
The binding permits stopping an owned recording after a disconnect or authority
teardown; it does not authorize start, Resume, playback, or other cloud management.
An application restart requires online validation to establish the binding again.

## Client contract and controls

`ComputerUseSnapshot.recordings` is optional for older snapshots. Each receipt
contains `recording_id`, `session_id`, `conversation_id`, `run_id`, `source`,
`status`, `started_at`, and `artifacts`.

| Field | Contract |
|---|---|
| `source` | `microphone`, `system`, or `mixed` |
| `status` | `recording`, `stopping`, `pending_export`, `saved`, or `failed` |
| Time | `started_at` and optional `ended_at` use RFC3339; `elapsed_ms` is optional |
| Completion | Optional `end_reason`, `error_code`, `partial`, and `can_retry_export` |
| Artifacts | Audio `artifact_id`, `kind: audio`, `mime_type`, and optional `source`; no native file paths |
| Stop/retry | Management action `audio_stop` requires both `session_id` and `recording_id` |

Activity controls match the selected conversation and run. With no current run,
only terminal recording receipts from that conversation remain visible. Settings
show the authenticated owner's scoped recording history. Local Build execution
and its activity filter use the same `DesktopRun.id`; the activity card is the
fixed top-level surface, separate from the invocation ledger.

Recording rows show source, duration, status, localized completion reason,
partial capture, independent Stop, and export retry when allowed. The full Stop
can preempt an outstanding audio export request. macOS retains the Swift status
menu; the Electron tray handles recording controls on Windows and Linux.

Audio downloads start only on a playback click. Artifact/client changes and
component unmount abort pending downloads; late responses cannot populate a new
scope, and loaded Blob URLs are revoked. Observation previews accept historical
Unix-second numbers and RFC3339 strings; invalid timestamps display a localized
unknown-time label without substituting the current time.

The shell CSP now declares `media-src 'self' blob:` for owned audio playback.
Before this change, real Chromium rejected a valid WAV Blob with
`NotSupportedError` and a `media-src` violation. The playback regression uses
generated PCM audio and the actual shell policy; it does not establish native
recording playback acceptance.

Cloud Marketplace V3 and Instances V2 use explicit endpoint, method, query, and
payload allowlists through the vault broker. The production desktop client uses
the scoped catalog. Scope drift and undeclared fields/routes fail before the
mutation, while server authorization remains authoritative.

## Development helper staging

The macOS development helper investigation reproduced Node 26.11.1 recursive
`fs.cpSync` overwriting an existing signed Mach-O executable while retaining its
inode and changing bytes visible through an already open file descriptor. Three
helper crashes reported `SIGKILL` / `Code Signature Invalid`. Staging now copies
to a fresh sibling bundle and replaces the destination directory, giving the
executable a new inode, with rollback if replacement fails.

Two staging regressions passed on both Node 22.22.3 and Node 26.11.1. They check
that an old open descriptor retains its original bytes, the replacement has a
new inode, and failed staging preserves the destination. Repeated staging of a
real signed temporary bundle also passed `codesign --verify --deep --strict`.
These checks do not establish that the subsequent native acceptance run passed.

## Automated verification

These are independent suite results, not an aggregate coverage or platform
acceptance claim. No overall coverage percentage was measured for this follow-up.

| Suite | Result | Scope |
|---|---|---|
| Python | 36 passed | Pause/resume flow and fresh-window recovery guidance |
| Rust core `--lib` | 75 passed | Core regressions, including recovery guidance |
| Sidecar `computer_use_v2` | 82 passed | Recording lifecycle, missing versus temporarily unavailable sources, offline cleanup boundaries, connector errors, and local Stop routing through both composite hosts |
| Execution-profile tool host | 3 passed | Permission intersection and preservation of wildcard and explicit MCP compatibility aliases |
| CUA adapter | 34 passed; 1 interactive binary test ignored | 16 unit and 18 contract tests |
| Portable native helper | 23 passed | Recording and lifecycle regressions |
| Swift helper | Structural harness passed; 5 IPC tests passed; 1 Locked Use test skipped | Structural capture/mixing checks and authenticated IPC |
| Desktop client | 63 passed across 10 focused files | Scoped marketplace transport, recording controls, missing-source messaging, audio URL lifecycle, activity, bridge, and renderer regressions |
| Audio playback CSP | 2 new tests passed | Real Chromium decodes a WAV Blob and advances playback; an unapproved remote audio URL is blocked before network access |
| Existing script CSP | 2 passed | Exact bootstrap hashes and restrictions remain intact |
| TypeScript | 3 compilations passed | Renderer, Electron, and fresh test compilation |

`zsh agi-stack/apps/desktop/cua-helper/test.sh` also completed helper and Locked Use
build/signing and emitted `AUDIO_CAPTURE_LIFECYCLE_OK`,
`CUA_ARTIFACT_RETENTION_OK`, and `CUA_STRUCTURAL_TESTS_OK`. The client checks include a real Chromium renderer
guest with typed image bytes; they do not validate Electron lifecycle or real
audio devices. Targeted Rust formatting and the desktop whitespace check passed.
Historical heartbeat and tool-argument repairs are outside this follow-up.

## Recovery and platform boundaries

- A sealed recording receipt already persisted in the sidecar database can be
  reopened and exported after helper exit or database reopen, while its owned
  source remains available.
- When Swift helper EOF or SIGTERM cleanup finishes normally, it stops capture
  and preserves sealed sources. The adapter's `Connection::abort` attempts to
  close stdin for up to 200 ms, then allows 500 ms for process exit before forced
  termination. Without a Tokio runtime it may terminate immediately, and stdin
  closure can time out before EOF. Swift stream shutdown may wait up to 3 seconds
  before mixing. EOF alone therefore does not guarantee
  sealing, and escalation follows the SIGKILL boundary: unsealed audio has no
  recovery guarantee. A receipt still held only in helper memory and never
  delivered to the sidecar database cannot be reconstructed after restart.
- Loss of a live recording without a sealed receipt becomes
  `failed` / `cua_recording_resource_unavailable` / `process_ended`; it is not
  reported as saved or automatically restarted.
- If export succeeded but the helper exited before `audio_ack`, the durable
  artifact remains available and acknowledgement is deferred. Cleanup does not
  launch a helper; sealed native source copies may remain. No offline garbage
  collection is implemented for that case.
- Windows and Linux changes have shared-logic tests, not platform-device
  acceptance. The Windows target check lacked a MinGW C compiler; the Linux
  target SDK was unavailable. Neither target has a successful native validation
  claim from this follow-up.

## Native acceptance

The macOS Electron client was launched through `make -C agi-stack run-desktop`
with an isolated application profile and workspace. The target was the dedicated
Computer Use Fixture application; audio input was a generated 440 Hz tone.
Microphone capture and other applications were excluded.

The local run established a real window observation and system-audio capture.
Independent recording Stop saved a 15.02-second PCM WAV (48 kHz, stereo, 16-bit)
with reason `user_stopped`; the parent task continued with another fresh window
observation. The persisted receipt reported 15,212 ms elapsed and a saved audio
artifact. After quitting and relaunching the client, the recording remained in
history and its actual UI audio player advanced to the end at 15.02 seconds.

During the same run, computer operation remained paused for more than 118 seconds
(conservatively measured). Resume first enumerated current windows, then obtained
a fresh observation. The enumerated window ID happened to be unchanged; this
proves refresh through enumeration, not replacement of the native window or
expiry of its identity. Recording did not restart and no interrupted action was
automatically replayed. A separate local run verified Stop after two observations:
the next observation received structured `user_stopped`, and the run entered
`ready_review` without an unknown-tool error, retry, or clarification request.

Negative checks included an execution profile that correctly excluded audio
start, and a round-budget exhaustion immediately after capture start. The latter
released capture and persisted `failed` / `audio_empty` / `session_ended`, without
claiming an audio artifact. Earlier helper signature crashes and Blob playback
failure led to the staging and CSP repairs above; subsequent native helper use
and actual playback succeeded.

The cloud plugin settings page loaded Instances V2 at revision 2 / `ready` and
the empty Marketplace V3 catalog without the former endpoint-policy rejection.
The first cloud Pause test exposed the path-alias cleanup defect described above:
the recording was correctly reported as failed, and no saved artifact was claimed.
After repair and a canonical client rebuild, Pause stopped a new system recording,
saved its 19.16-second WAV, and displayed the localized `user_paused` reason. The
actual UI player advanced through the complete recording.

That cloud run remained paused for over 113 seconds (conservatively measured).
The backend confirmed that Resume woke the same paused control generation. The
first resumed native call was `computer_list_windows`, followed by a new snapshot
not present before Pause, with no automatic audio restart. The later attempted
clarification was rejected by the approved run's tool permissions; the test did
not complete its proposed second recording.
Computer Stop ended native execution and the parent reached `ready_review` with
`user_control_handoff`, `goal_achieved: false`, and `control_outcome: user_stopped`.

A separate cloud task verified independent recording Stop. The activity card
changed from recording to saved with reason `user_stopped`; subsequent fresh
observations confirmed that the parent remained running. The backend recorded
seven successful fresh observations after independent Stop, no subsequent audio
start, and a final `ready_review` run with all three plan tasks complete. Its
actual audio player advanced through the complete 15.04-second recording. Both
cloud WAV files were verified as 48 kHz stereo, 16-bit PCM.

Retrying the earlier failed cloud receipt in the actual settings UI produced
the missing-source message and removed the retry button without opening capture.
The original Pause reason remained visible. After client exit, read-only receipt
inspection confirmed the two successful cloud recordings as `saved`, respectively
`user_paused` / 19,353 ms and `user_stopped` / 15,231 ms. The earlier failed receipt
retained its identity and timestamps with `cua_audio_source_missing` and
`can_retry_export: false`.

Both local and cloud plugin settings were returned to installed-but-disabled,
with microphone, system audio, and Locked Use off and no application grants. The
test cloud workspace's permission mode was restored to `ask`, then its actual
settings dialog archived it; the backend confirmed both states. The previously
selected cloud workspace was restored before logout. Standard artifact deletion
removed only this run's 26 cloud screenshots; their download routes rejected
access afterward, the other 57 historical artifacts were unchanged, and the three
cloud conversation audit trails were preserved.

The owned Electron/sidecar, fixture, generated-tone playback, and development
backend processes exited. The isolated profile, local workspace, fixture bundle,
test logs/audio, and native recording roots identified from that profile were
removed. The preexisting helper and unrelated infrastructure and worktree changes
were preserved. No commit was created.

Automated results must not be read as successful microphone, menu, lock-screen,
or cross-platform native acceptance.
