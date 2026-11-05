# Computer Use implementation and validation: 2026-10-29

This update records the compatibility additions and executable validation from
the 2026-10-29 investigation. The guided local CDP task and short source-specific
recording checks passed. Full browser-provider, cloud execution, recording
recovery and lock-continuity acceptance is not claimed.
The earlier behavior and authorization model remain documented in
[Persistent Computer Use](computer-use-repl.md).

## Reference installation and analysis limits

The inspected reference is ChatGPT.app **26.1023.50603**, containing
`@oai/cua-repl` **0.1.2**, `@oai/cua` **0.2.6**, `@oai/sky` **0.7.13**, and native
Computer Use service **26.1022.1001641**. The requested REA setup completed as
`ready` without configuration changes. Readable shipped JavaScript, declarations
and package metadata supplied the facade findings. No native decompilation engine
was available, and REA's semantic analysis remained partial. Parsing shipped
files does not establish recovery of every native behavior or private service.

The reference exposes persistent JavaScript entrypoints, raw computer operations,
bound app/tab objects, browser-specific capabilities, text/image/audio output,
and host-supplied execution context. Connectors remain a separate host MCP
capability; the reference does not establish a general `cua.connectors` or
`cua.mcp` namespace. Lock-related declarations and native symbols support a cover
and temporary-unlock design; they do not prove application control while the OS
session remains locked. These are static reference findings, not a successful
reference-app recording, connector mutation, unlock or fault-recovery run.

## Implementation changes

### Persistent facade and native compatibility

- `initialize()` now emits fresh inventory. Documentation uses stable output
  item identities, and replay observes the current host request context.
  `nodeRepl.requestMeta` is read-only; final result previews are bounded while
  variables retain their original values.
- Raw `cua.computer` entrypoints cover application listing, authorized launch,
  app observation and structured input alongside the bound app API. Input
  remains tied to the latest admitted snapshot and window. Raw held durations
  use seconds; bound `durationMs` values use milliseconds.
- Browser aliases, tab mentions, AX access, events and capability documentation
  retain provider and tab identity. Unsupported provider capabilities fail
  explicitly. Browser selection uses configuration and structured identities;
  destination words do not classify the user's account or intended browser.
- Managed-process and kernel lifecycle tests cover reset, outstanding work,
  cancellation and result bounds. None of these additions gives JavaScript
  authority to supply its own user, run, device or approval identity.
- A changed-source continuation under the same authorized execution retains
  the suspended cell and exact approval binding. Authenticated revision changes
  keep the original pending operation; byte-identical source resumes its Promise
  without replaying completed actions. Identity changes remain fatal.

### Browser providers and configuration

Chrome/Edge extension profiles, the Electron in-app browser, attached MCP Apps
and explicitly configured local CDP browsers share the existing browser tool
host. The CDP provider supports HTTP discovery and direct WebSocket endpoints.
Endpoints must be loopback IPs or exact `localhost`; resolution must produce
only loopback addresses. Discovery redirects and returned WebSocket addresses
are revalidated, remote proxies are disabled, and connections use checked peers.

Each configured CDP provider has a canonical UUID and a separate connection
generation. String CDP target IDs map to the host's integer tab IDs. Reconnecting
rotates the live identity and invalidates old handles. Flattened target sessions
are bound to their owning tab; root and descendant sessions initialize automatic
attachment, including nested out-of-process frames. A cancelled root attachment
can finish its missing initialization without replaying an application action.

Settings can add, remove and enable local endpoints and select a default
browser. `cdp_endpoints` defaults to an empty list; `default_browser_id` defaults
to `iab`, so older configuration remains readable. Saved default references use
stable provider/profile identity rather than a connection generation. Offline
defaults remain visible; deleting the selected CDP endpoint selects IAB.
Configuration updates use the existing plugin authority and serialized native
configuration path. Sidecar recovery restores only acknowledged configuration
and checks the endpoint list and default reference as well as prior flags.
Cold application starts load validated provider, endpoint, port and default
preferences from a versioned private file in the application's data directory.
Writes are staged and atomically committed before a setting is acknowledged.
Global bridge and full-CDP enablement remain off on a cold start; each endpoint's
enabled preference is retained and takes effect after global bridge opt-in.
Tokens, generations and run leases are never saved in this preference file.

CDP does not advertise extension management, history or IAB visibility support.
It does not supply OpenAI's private browser services. Generic MCP tools remain
available through their existing scoped catalog, allow-lists and permissions;
the Calendar/Contacts/Messages shortcut roster does not restrict that catalog.
Standard `structuredContent` reaches the model, including tools with an empty
content array and cached replies; App-only `_meta` stays outside the model view.
OAuth connect and refresh reject invalid or overflowing expiry durations before
persisting grant changes.

### Audio compatibility and bounded output

The system-audio compatibility API provides `start_audio_recording()` and
`stop_audio_recording()`. Stop returns `{filepath, bytes, data_url}` for its owned
24 kHz stereo WAV. The extended microphone/system/mixed API remains available.
Source-specific consent, recording limits and independent Stop behavior remain
in force; resuming a session does not start another recording.

Local OpenAI-protocol providers expose an explicit audio-input checkbox for each
enabled model in Settings. The existing revision-bound provider update persists
`audio_input_models`; response decoding and connection/activation edits preserve
the declaration. Disabling a model removes its declaration. Unsupported
protocols and undeclared model IDs cannot gain audio-input support through this
control. Declaring support does not establish a model's actual audio understanding.

The Volcengine Ark preset now binds the existing compatible protocol to the
official endpoint and its environment credential reference. Cloud Settings maps
the exact audio model declaration into the existing provider `config` field.
Cloud validation uses the exact primary, small and secondary model IDs;
`allowed_models` remains a prefix filter. Desktop model edits preserve that
filter, and audio updates require the public configuration snapshot to retain
existing tuning and retry parameters. The actual Python response builder and
validator are exercised by the desktop contract integration test.
The Python Ark adapter no longer omits declared audio inputs; oversized inputs
fail explicitly, and Rust HTTP/SSE errors retain bounded, credential-redacted
provider details. Audio failover skips candidates without a declaration.
See [Ark configuration and validation](volcengine-ark-audio.md) for the current
protocol limits and actual provider canaries.

Large recordings use bounded artifact reads rather than a large control frame.
Each read requires the recording's exact owner, native context and engine
session, a saved receipt, and a receipt-owned artifact in the same conversation.
The client checks recording/artifact identity, MIME, size and consecutive offsets
for every chunk. Emitting the original owned audio object uses a basename in the
kernel's private temporary directory. The host opens it relative to a pinned
directory descriptor, rejects symlinks and non-regular files, validates the WAV
header and size, and copies to a new private artifact. Arbitrary large inline
bytes do not gain this file-output path.

## Executable validation

| Area | Result and boundary |
| --- | --- |
| Node facade | 80 tests passed; source-only line coverage 97.59%, branch 88.17%, function 83.26%. Tab, native App and raw `set_value` regressions reject missing or non-string values before RPC while preserving empty strings and original content. These test the maintained implementation, not complete reference equivalence. |
| CDP | Latest 9 tests passed with the real Chromium test explicitly enabled. Production browser-host operations covered DOM/input, three local sites with two nested OOPIF levels, successful/refused target closure, disconnect, stale generations, foreign sessions, cancellation and loopback discovery constraints. |
| Browser configuration/UI | 42 focused Node tests passed, including rendered offline-default settings, configuration authority, stale status reads around enable, queued cancellation and acknowledged sidecar recovery. Renderer and Electron TypeScript checks passed. |
| Browser cold restart | Four Rust preference tests passed, including save in one application-runtime process and restoration by a fresh runtime, private file modes, rejected malformed settings and failed writes. Same-Supervisor acknowledged crash recovery separately passed all 16 tests. Native cold restart restored the saved local CDP endpoint and its stable default reference, with the global bridge off; explicitly enabling the bridge reconnected CDP. This covers that configuration recovery, not native restart acceptance across every provider. |
| Rust server identity/catalog | 92 identity-related tests passed: 64 Rust, 27 desktop and one real PostgreSQL temporary-database regression. Actual HTTP → Electron projection → renderer decoding and subsequent native Rust-server login passed after restoring `global_roles` and `is_superuser`. Unbound conversation filtering separately passed 16 Rust tests, one real PostgreSQL test and 26 frontend tests. Workspace-directory HTTP 404 and a new-thread `Invalid agent conversation response` remain native blockers; no model task passed. |
| Provider audio declaration | Latest 81 focused provider tests passed, covering save/clear/omission, protocol and model validation, response decoding, edits, rendered local/readonly controls, exact cloud primary/small/secondary rosters and public configuration preservation. Renderer, Electron and test TypeScript builds passed. The public configuration projection helper reached 100% line, branch and function coverage. All three sources now have actual native model audio-input results; the positive microphone transcription contains a word substitution. |
| Review feedback UI | 156 timeline, message-action and rendered feedback tests passed, plus renderer and test TypeScript checks. Explicit native `request_changes` user role/content now render as feedback; approval-only events create no empty user bubble, and live/history merging preserves one feedback bubble. The canonical restart loaded this fix. |
| Python native bridge | 150 catalog, bridge, claim, step and native-tool tests passed after adding the missing first-party `computer_locked_use` declaration as a mutation. The actual App's device registration subsequently became ready. This does not establish approval continuation or browser writes. |
| CUA adapter | 17 unit, 31 contract and three cross-language tests passed; one native interactive scenario remained explicitly ignored. The real Rust host's complete tool catalog passes Python's production registration, schema and effect checks before the first storage mutation. CI explicitly prepares locked Python dependencies and runs this test; it does not install dependencies inside the test or silently skip it. |
| Swift helper | `test.sh` passed the exercised structural, recording, installer rollback, broker and coverage checks: nine broker groups and 419 coverage checks. Protocol output recorded eight cases and one skipped scenario. This does not establish temporary unlock/relock acceptance. |
| Locked Use release | The six-line production host change retains current execution, owner, native-session, effect and configured-capability checks while allowing `enabled:false` cleanup without another device Once prompt. `enabled:true` still requires fresh Once consent. The real ScopedHost regressions and existing suites passed 42 distinct tests: 31 Locked Use plus 16 consent, with five shared tests. No actual lock/unlock/relock pass is claimed. |
| Generic MCP | Three scoped-catalog tests passed. A non-shortcut tool completed an actual stdio protocol call with structured-only output and cached replay; App-only metadata stayed private. |
| MCP OAuth | Invalid expiry boundaries and the existing real HTTP PKCE/callback/refresh/rotation/scope/cancel/disconnect integration test passed. |
| Full sidecar suite | Latest 1,373 tests passed, zero failed and three interactive scenarios were explicitly ignored after the Ark, continuation and preference fixes. The latest nine CDP tests separately included the real Chromium scenario. |
| Plugin contract gate | Still fails three literal-key checks: two imported service constants in Rust `target_modules.rs` and the forwarded Python policy event parameter. The same HEAD sources reproduce these failures; they are baseline static-scanner limitations, not a passing gate or a new regression from this round. No source suppression was added. |
| Ark provider | Latest 81 focused desktop provider tests and 183 Python provider/audio tests passed. The earlier audio-policy/artifact-preparation coverage measurement was 95.50%. The Rust HTTP adapter passed 59 tests, including ordinary/streaming audio, tool actions, provider errors and `finish_reason` diagnostics. Actual text and neutral synthetic-WAV canaries returned HTTP 200 on the account's already-enabled `doubao-seed-2-0-mini-260428`; the synthetic-audio response reported 24 audio input tokens. Three-source native capture/save/playback and model audio input have actual results, including a later positive microphone native transcription. The separate blind HTTP control is not counted as native task completion, and exact ASR accuracy is not claimed. |
| Python completion handling | 297 tests passed after 25 new finish-reason regressions; the relevant helper measured 96.67% coverage. Known `length` and `content_filter` results are rejected across empty deltas, valid JSON, tool completion, repair and retry paths without splicing a partial answer into a later response. API reload retained health, authenticated current-user access and the migration head. |
| Python graph initialization | The deferred-embedding change passed 430 tests, including 36 new tests; the relevant port implementation measured 100% coverage. The reloaded native path now reaches model and device calls. Graph recovery alone is not a cloud CUA pass. |
| Python tool schema transport | 395 related tests passed. Three native-permission literal fields now declare `type: string`; task-write conditional literals use explicit types too. Actual worker-built tools pass conversion and ordinary/SSE loopback HTTP serialization checks, without provider-name branches or executing their tools. |
| Goal judgment | 589 related tests passed, with relevant coverage of 89.88%. Judgment reads current generation parameters, uses automatic tool selection while requiring exactly one valid structured judgment call, and retains one bounded expansion to 4,096 tokens for explicit truncation, including nested typed finish errors. No missing, prose or malformed verdict is accepted as completion. |

These focused suites overlap; their counts are not added into a single total.

The real Chromium checks used owned temporary profiles, local fixture servers
and owned process groups, which were cleaned up. They establish the provider's
execution chain and nested-frame behavior, not a real model completing a task
through the Electron client.

## Native Electron work and remaining boundaries

The client was launched through the canonical repository-root command,
`make -C agi-stack run-desktop`, using an isolated QA profile. In the actual
Settings UI, the operator saved and connected the local CDP provider
`CUA Native1029` on port 60313, selected it as default, and observed Chrome,
Edge, IAB and CDP inventory entries. This verifies UI configuration and an actual
provider connection. The native-agent CDP completion below supplies a separate
execution result.

A local Ollama/Qwen run generated a plan but submitted execution arguments that
failed the tool schema. It performed no browser operation and is not counted as
successful native-agent acceptance. A canonical restart with the same profile
was then started using private environment injection for the supported Kimi
provider and one Apple Development signing identity. Native cold restart
subsequently restored the saved local CDP endpoint and its stable default
reference while leaving the global bridge off. Explicitly enabling the bridge
reconnected the provider. A real Kimi execution then exposed a changed-comment
approval continuation failure; its suspended-cell recovery and authenticated
revision handling were fixed and passed the 45-test REPL lifecycle suite.
The subsequent native Kimi task completed an exact guided script against the
local loopback CDP provider. Cell `d7a198d6-88b5-46a6-a20b-5eb2ed6a253b`
continued its original Promise through five exact approvals for `tabs.new`, the
`127.0.0.1` origin, `tab.claim`, `fill` and `click`. Actual tool output was
`CDP_NATIVE_1029_OK | clicks=1 | trusted=true`. Screenshot artifact
`cua-image-777c3d87-2bb1-432d-ba1c-ef447d34688b` was `image/jpeg`, 14,321 bytes;
the operator viewed it and confirmed the fixture state matched. The native UI
showed the approved run completed. This result covers a guided local CDP task;
it does not establish unguided model autonomy or native task completion across
Chrome, Edge, IAB and MCP Apps. No credential value is recorded here.

Ark network access was restored by correcting the active Clash rules: five exact
Ark-related domains use `DIRECT`, while other traffic keeps the `MATCH` route to
`GLOBAL`. The actual catalog then returned HTTP 200 with 138 models. Text and
neutral synthetic-WAV requests to `doubao-seed-2-0-mini-260428` both returned HTTP
200; the latter reported 24 audio input tokens. This generated WAV was not a
physical recording.

In the native Settings UI, the operator created **Ark CUA QA1029** and saved the
model's explicit audio-input checkbox. The Ark mini browser run subsequently
submitted incorrect plan/tool arguments and was cancelled through the native UI.
It is not counted as browser task completion. The later Kimi CDP result does not
change that Ark result.

The native audio task then captured one system-audio recording from an external
`afplay` playback of a neutral fixture. Recording
`33CFA8DA-EE25-4482-8C90-6C859A8991ED` saved artifact
`cua-audio-d190b77e-0868-5b7e-a23b-8ff750143c55`. Its receipt reported `saved`,
`source: system`, `sample_rate: 24000`, `channels: 2`, `encoding: pcm_s16le` and
`end_reason: duration_limit`. The WAV measured 484,096 bytes and 5.000 seconds,
with private file mode `0600`, peak 11,780 and RMS 2,177.92. A subsequent REPL
output copy is derived from this recording and is not counted as another capture.

The native preview played to five seconds, and Ark transcribed the captured
audio as “Violet seven. Computer use native acceptance violet.” The prompt did
not supply the phrase. Following a canonical cold restart, **Settings → Plugins**
loaded the same recording and played it to five seconds again. This short
system-audio capture, understanding, playback and restart-recovery chain passed.

The combined three-source task nevertheless ended after the first segment.
Submitting a request for changes resumed the run, which then failed with
`round budget exhausted`. It remains a failed combined run. Later individual
source checks supplied the following results.

The initial quiet microphone recording (original artifact prefix `e36a7ccc`)
saved 474,500 bytes and 4.900 seconds with master output muted. Re-emitting this
owned audio to Ark through native review
feedback correctly produced a silence judgment. Its REPL output copy with prefix
`5022` is not counted as another capture.

The positive microphone retest temporarily set master output to 25% and unmuted.
Original artifact `cbbc35dd-039b-5c6f-b360-d33cd34ddac1` saved 474,500 bytes and
4.900 seconds, with peak 3,225 and RMS 576.24. Capture and emission succeeded,
but the task failed at the round budget. A blind HTTP ASR control returned HTTP
200 and “computer use native acceptance file seven”, reporting 32 audio tokens.
This control is separate from native App understanding acceptance. The REPL
copy with prefix `1a50e57b` is derived from the same recording. Native microphone
preview playback was observed through 4.9 seconds.

The native Kimi mixed-source task completed two steps in the same Promise and
saved original artifact `2e15082c-060c-5856-a668-24d9a3b1cb71`: 484,096 bytes,
5.000 seconds, peak 6,013 and RMS 1,077.37. The native player ran to completion.
The operator left the run at `ready_review`, selected Ark through the normal
model menu, and used `request_changes` solely to emit the owned `b.media` again.
The actual native App response was:

> 补充原生音频理解验证任务完成，混合源录音转写结果为：Tunes violet seven computer use native acceptance，可清晰识别上述音频内容。

The run was then approved and completed. This establishes native mixed-source
understanding alongside the earlier system-audio result.

A later Kimi microphone task saved original artifact
`cua-audio-3daa1137-313b-5572-9f4a-f28b7c0ab298`: 1,924,096 bytes and 20 seconds,
24 kHz stereo PCM16 WAV, private file mode `0600`, peak 4,415 and RMS 521.25.
REPL output `6643cab1-0a7a-4a33-9f80-a17f348a7335` is a copy of the same capture.
At `ready_review`, the operator selected Ark and submitted `request_changes`
solely to emit the owned `b.media`. The actual native App response began
“Acceptance file seven. Computer use native acceptance file seven”. This is a
positive microphone native audio-input/transcription result. The fixture word
“violet” was recognized as “file”; this is not a perfect-ASR result.

All three sources now have actual native capture, save, playback and model
audio-input results. Native AX also confirmed the new microphone preview played
through the full 20 seconds. The attempted independent Stop click on that task
did not execute because its AX target had expired, and its receipt reports an
assistant stop. That earlier attempt is not a successful independent Stop.

A separate system recording with a 45-second maximum passed independent native
Stop. Capture began at 14:54:36. Fresh AX observed the independent Stop button
at `0:08`; the next call refreshed AX and clicked it. The UI then saved at
`0:17` with the user-stopped label. The model's final receipt reported
`source: system`, `status: saved`, `end_reason: user_stopped` and artifact
`cua-audio-cdc1dead-58b7-5435-946a-abb001c98731`. Its file measured 1,651,456 bytes
and 17.16 seconds, 24 kHz stereo PCM16 WAV, mode `0600`, peak 11,706 and RMS
2,069.19. The original Promise completed normally and the task reached
`ready_review`, without cancelling the run. Native AX subsequently showed the
preview at its full 17.16 seconds and back at the Play button, confirming
complete playback.

Native computer-use Pause was then exercised during a system recording that
started at 15:01:35. Fresh AX showed eight seconds; the next call refreshed AX
and clicked **暂停电脑操作**. The UI reported the recording saved at `0:15`,
**已随电脑操作暂停而停止**, **已暂停** and **恢复电脑操作**. Raw artifact
`cua-audio-be2b2c80-656f-54ab-82ab-65f9dd2fcf81.wav` measured 1,497,856 bytes,
15.56 seconds, 24 kHz stereo PCM16, mode `0600`, peak 11,704 and RMS 2,139.36.
The cell's next `audio.status` RPC returned
`{retry_allowed:false,status:user_paused,type:computer_use_control}`. Native
preview subsequently reached the full 15.56 seconds and returned to the Play
button. No Resume action, retry of the old cell or new recording start was
issued.

This Pause result concerns native computer-use input and recording authority.
It does not mean the Node process was immediately killed: the pure JavaScript
timer continued until the next native RPC returned the typed paused control
result. Independent recording Stop had allowed its original Promise to finish
normally. The operator later used Stop response to cancel the Pause QA run;
the recording/control checks passed, and that run is not a model-completed task.
After the physical tests, master output was restored to its original 81.25%
and muted state.

The supplemental understanding checks retained the original conversation and
owned media through the `ready_review` feedback path. Completed build runs
reject ordinary new input; no cross-conversation saved-read bypass was used.
Ordinary local attachment upload returned HTTP 501 and is not claimed as
supported audio input.

Cloud native acceptance is still in progress. Python-cloud login and workspace
creation succeeded in the actual client. Its first task failed before a model
call because all five prepared memory tools were missing: graph initialization
had eagerly required an embedding provider and left the graph runtime absent.
The change in [graph factories](../../src/configuration/factories.py) and
[deferred embedding](../../src/infrastructure/graph/embedding/deferred_embedding.py)
preserves graph composition and defers embedding-provider resolution to an
operation that needs it. The 430-test result and API reload were followed by
native model and device calls. Disabling only the memory-tool provider is not a
recovery path: the enabled V2 memory contribution still requires its five tools.

The device's first real catalog was also rejected because Python omitted the
declared `computer_locked_use` tool. The mutation declaration and real
Rust-host-to-Python regression now pass, and the existing native App connection
became ready. Subsequent native requests exposed strict tool-schema and goal-judge
parameter/finish handling failures; the corrections above passed their component
and loopback transport tests. The fourth Python-cloud build actually executed
`getState()` and read the configured CDP provider. Its browser cell then returned
a permission request, but `request_permission` failed with **Native permission
target is not pending in this session**. The independent host permission record's
transfer is under investigation. This build has not completed a browser write or
screenshot, and is not a passed cloud browser task.

The Rust-server native attempt returned silently to login because its current-user
response lacked `global_roles` and `is_superuser`. The
[current-user projection](../../agi-stack/crates/adapters-postgres/src/user_store.rs)
now reads the actual database scope, and the HTTP-to-renderer chain passed.
The reloaded server answered health checks and actual native login subsequently
succeeded. The workspace directory still returned HTTP 404. The unbound catalog
fix passed component and real PostgreSQL checks, but creating a new native thread
currently fails with **Invalid agent conversation response** and is being repaired.
No Rust-server native model task has completed. Python's
[completion diagnostics](../../src/infrastructure/llm/completion_finish.py)
and these identity repairs do not convert either cloud route into a passed task.

Locked Use native preflight confirmed local foreground mode, an installed but
inactive component, and granted Accessibility, Input Monitoring, Screen Capture,
microphone, system-audio and Locked Use permissions. A cold restart retained no
old lease. The native UI contains version 2 of the concrete lock-fixture draft;
it remains unapproved. No enable, system lock or action-time user confirmation
has occurred. The scoped false-release fix in
[the host](../../agi-stack/apps/desktop/sidecar/src/local_runtime/computer_use_v2/host.rs)
is loaded. Cloud execution repairs and replay precede the proposed lock test. Its
temporary unlock, fresh fixture write, read-only hold and observed physical
relock therefore remain planned, not executed.

The following remain unverified in this round:

- Resume after Pause and remaining recording failure/recovery paths. Independent
  native recording Stop and computer-use Pause passed, including complete
  playback of their saved recordings; the earlier microphone click did not execute.
  The separate HTTP microphone control and successful individual source checks
  do not turn the earlier combined run into a pass or establish exact ASR
  accuracy.
- Locked Use temporary unlock, continued fixture operation, observed relock and
  native fault injection. The existing mechanism uses a full-screen cover and
  temporary unlock; it makes no zero-exposure guarantee if the cover is killed.
- End-to-end native execution through the Python cloud and Rust server chains;
  their component and provider HTTP checks do not establish this result.
- Production signing/notarization and remote production deployment, plus native
  acceptance on other operating systems and untested browser combinations.

Seven pre-existing Swift Locked Use modifications were preserved. Passing their
component tests does not convert the outstanding native lock scenarios into
completed acceptance. No parity manifest, route inventory or manual evidence
promotion gate was introduced.
