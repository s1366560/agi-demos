# macOS background input

Implementation and native acceptance as of 2026-10-22.

The trusted plugin-instance setting selects `background` or `foreground` input.
New instances request background mode; foreground mode requires an explicit user
choice. Changing mode revokes existing native sessions before new work can use the
new value. Model action parameters cannot supply the mode, generation, or an
arbitrary process ID. Windows and Linux implement IPC 3 and advertise background
input as unsupported. Neither native nor host code silently falls back to HID.

macOS binds each input generation to a verified process birth identity and native
window. A private CGEvent source maintains independent keys, buttons and modifier
flags. Targeted events use `CGEventPostToPid`, native window fields and logical
window coordinates. Unicode insertion, physical key names, AX actions and
clipboard operations retain separate semantics. Key names identify physical ANSI
positions interpreted by the target's active input source. Layout and input-source
identifiers are reported separately; their Carbon queries run on the AppKit main
thread to avoid a HIToolbox abort during input-source changes. Literal Unicode
does not simulate IME composition. Secure Event Input rejects background dispatch.
`MEMSTACK_CUA_DISABLE_BACKGROUND_INPUT=1` disables the private input path.

The current private-source background path does not alter the global pressed-button state. This is
an intentional isolation boundary, and it limits applications that read that
global state instead of the delivered event. The current WebKit and Electron
fixtures receive trusted mouse events and edit the correct field, but their DOM
drags do not complete: both report `mousemove.buttons == 0`. Their ordinary event
builders read `NSEvent.pressedMouseButtons` (see the
[Chromium builder](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/components/input/web_input_event_builders_mac.mm)
and [WebKit factory](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/Shared/mac/WebEventFactory.mm)); the inspected local AppKit path reads
HID state (state ID 1), independently of the delivered event's private state.
A dispatch receipt is not a
drag-success claim. The ordinary fixture test continues to fail on this outcome;
the explicit `--expect-global-button-limit` variant tests the reproduced limit and
remaining operations separately. An agent must observe the result and explain
the limitation; changing to foreground mode remains a user choice.

The focus guard filters verified process-focus notifications and redirects
misdelivered keyboard events to the verified previous recipient. It does not
prevent arbitrary WindowServer application activation. A controlled target
calling `NSRunningApplication.activate` still becomes the global frontmost
application. The guard pauses when that transition is reported and does not
activate the previous application to conceal it. Capabilities explicitly report
`global_activation_suppression: false` and
`global_button_state_emulation: false`. The current backend does not provide
universal background dragging or absolute prevention of application-initiated
focus changes. The investigated external interfaces have not established a way
to provide those behaviors while preserving the current input-isolation boundary.
The follow-up native probes attempted external window tags 16 and 16/20/21;
the setter returned success but readback remained unchanged, and explicit target
activation still changed the frontmost application. No production change relies
on those ineffective tags. A reference native Computer Use controller also
reproduced the Electron drag limit inside the actual drag region: trusted down
reported one button, movement reported zero, the page remained `drag idle`, and
the independent observer recorded unchanged foreground, cursor and global input
state. The equivalent WebKit probe also delivered movement with zero buttons.

Changing windows, pausing or rebuilding the input backend invalidates the old
generation and observations. Only a successful authorized observation can advance
the host's binding; a late observation cannot overwrite a newer recovery. Window
movement invalidates the old geometry. Resume requires another observation and
does not replay an action whose outcome is unknown. Both normal cleanup and the
surviving input watchdog use the same route and process-birth check, so background
release cannot send global key-up events or target a reused PID.

Window enumeration preserves opaque IDs using the process birth and exact native
window ID. An AX wrapper change does not rename the same window. A window omitted
from AX enumeration on another Space remains addressable only while its retained
AX object answers a live role/PID/window-ID query and WindowServer confirms the
same owner and valid current bounds. Titles and matching geometry cannot recover
an identity. Enumeration errors preserve the error and do not publish a new cache
or input generation; closed windows and changed process identities are rejected.

The separate `native_input_telemetry` stream carries owner context, generation,
sequence, target, cursor coordinates and complete held-input state. It contains no
typed text. Swift and sidecar output writers prioritize control replies and
lifecycle notifications; input updates retain only the latest frame per session.
A bounded blocked pipe fails closed instead of continuing a partially written
frame. Queue-overflow cleanup runs independently of the input producer so that
releasing held input cannot reenter its nonrecursive lock. A real-pipe regression
reproduces the old failure and verifies one completed cleanup after the fix.
The authenticated sidecar stream feeds scoped Electron/preload
subscriptions. Renderer presentation batches updates with animation frames and
clears retired generations on pause, stop, mode changes and owner retirement.
The overlay labels dispatch receipts as dispatched. Application outcomes require
a fresh observation; receipt alone does not establish a successful edit.
Configuration requests clear the current display while pending, but a failed
mode change, disable or uninstall does not retire an input generation that the
authoritative session still reports as active. A successful stopped snapshot
retires it permanently and rejects late input frames.

The software cursor is an inert nonactivating window, ordered relative to the
target window and hidden when its point is occluded. It tracks the target's current
geometry without moving the system pointer. User input in another application
does not pause background work. Input directed at the target pauses the owned
session and releases its holds. Sleep, screen lock and session resignation also
stop sessions and remove presentation.

The opt-in background fixture uses two independently signed applications and a
separate system-state observer. AppKit, WebKit and Electron content exercise real
input receivers, with assertions on the specific edited field and delivered
coordinates. Synthetic external-input tests are explicitly separate from physical
keyboard/trackpad acceptance. Current native acceptance results and remaining
platform limits must be read separately from the earlier foreground results below.

The 2026-10-21 native checks ran on macOS 27.0.1 (26A434), arm64, with two
Retina displays. Universal arm64/x86_64 compilation retained the macOS 14.4
deployment target and passed strict bundle-signature verification; this does not
claim a macOS 14.4 or Intel runtime test. Swift structural checks and seven helper
protocol tests passed; the separate opt-in Locked Use test was skipped.

The human-assisted `physical_input_test.py` passed with 32 background iterations:
all 64 key-down/up events had the correct source, key and modifier state, and the
final target field matched exactly. The independent observer saw 3,241 system
state changes and 16 intervals where the user physically held Shift across a
background action. All observed foreground states remained the Guard application.
The user typed in that application and confirmed no cursor jump, focus theft or
cross-window typing. Mouse movement counts alone are not a proof of an unchanged
trajectory; this result combines the human report with the separate fixed-pointer
isolation checks.

The software-cursor regression verifies visible placement after moving the
target window and hiding under a different window of the same application.
Public accessibility hit-testing avoids treating the Dock's transparent,
full-display WindowServer rectangle as an opaque obstruction. The focused
activation regression reproduces global activation, then verifies a pause and
release of owned Shift/button holds. After Stop, an explicitly simulated external
HID key goes only to the foreground Guard, with no stale keyboard redirection.

The final AppKit fixture passed real drag delivery, all three mouse buttons,
scrolling, Chinese and emoji insertion, cross-call modifiers, cancellation and
watchdog recovery. A second-display run also verified that target exit publishes
paused state with empty holds before any cleanup request. WebKit and Electron
passed their explicit global-button-limit variants; WebKit additionally opened
its native context menu and closed it with Escape. A menu diagnostic captured
real lost/returned key-focus notifications while an external simulated key went
only to the foreground Guard. The foreground regression passed automatic pause
on external input, preservation of an externally held Shift, stale-generation
rejection, and Stop/SIGKILL key and drag recovery.

Real French-layout acceptance passed with AppKit, WebKit and Electron receivers.
The physical keys named `a`, `q` and `shift+a` produced `q`, `a` and `Q`; literal
Chinese, accented text and emoji matched exactly. The system pointer, foreground
recipient and global held state remained unchanged. Each run restored the
original Sogou input source and disabled the temporarily enabled French layout.

Human-assisted Sogou acceptance observed real uncommitted `ni`, then verified
that background Unicode, arrow and Shift events left the foreground marked text
unchanged. The user continued the same composition with `hao` and committed
`你好`. Native event and marked-range records establish this composition,
isolation and continuation result. The driver then checked key release too early,
on Space key-down; it now waits for physical key-up. That final driver correction
was not followed by another human IME run. This result does not advertise
synthetic IME composition support.

The 2026-10-22 real-lock scenario passed end to end. Before the operator locked
the Mac, the target and telemetry both confirmed held Shift and left-button
state. The independent OS observer then confirmed a real lock and cursor removal;
input stopped with empty holds, and target releases came from the helper PID.
After the operator unlocked, the old session rejected resume, reset and later
input. The same helper created a new session with a different input generation,
observed released target state and successfully dispatched fresh input. The
driver permits a bounded retry only for the exact transient
`accessibility_unavailable / AXWindows / -25204` response during recovery.

The 2026-10-22 Space scenario passed after the window-identity repair. A separate
native observer established the cause: after a real Space transition, AXWindows
successfully returned an empty list while the retained AX objects, native window
IDs, WindowServer owners and process birth remained valid. The repaired helper
kept the same opaque window ID, captured the off-Space window and inserted the
exact expected text without changing the stable foreground recipient, system
pointer or global held state. The assistant cursor remained hidden. After the
operator returned, the text persisted and fresh background movement restored the
cursor, again without global input changes. Real Space epochs and WindowServer
visibility were checked in both directions.

The driver distinguishes a user-input pause from a terminal stop and waits for
matching session/generation notifications. Its optional operator gates and a
one-second quiet baseline prevent the test from starting while the operator is
still confirming a switch; changes during tested actions still fail. Earlier
post-fix attempts completed the edit but failed the pointer-stability assertion
and were not counted as passing runs. After the real-lock scenario, the complete
AppKit background-input regression also passed. The operator performed unlocking;
no Locked Use installation was performed.

The native Electron client was launched from the repository root with
`make -C agi-stack run-desktop`, using a disposable application profile and
workspace. Local sign-in, plugin enablement, explicit foreground/background
selection, and cold-restart persistence passed. A real Kimi model requested
session-scoped observation through the normal native approval card; after
approval, the target icon and current fixture-window preview rendered correctly.
The first input attempt was rejected by the approved `workspace_write` run
profile before reaching the helper. That rejection does not establish input
success; tool-profile approval and native application consent remain separate.

A subsequent MiniMax-M3 run obtained exact once-only click/text tool grants and
session-scoped native observation/control consent through those same UI cards.
It clicked the observed background field, inserted `NATIVE_INPUT_d501b647`, and
observed the exact resulting value `Fixture 2 textNATIVE_INPUT_d501b647`.
An independent AX read confirmed that value. The authenticated Electron/preload
subscription received 22 coalesced input updates, and the actual preview showed
the assistant cursor, dispatched label, and empty final held-input state. The
separate system observer recorded no foreground, cursor or global held-state
change throughout this run. Native UI pause/resume was exercised during an
earlier live run. Changing the input mode after the successful run removed its
native session and cleared the cursor presentation; background mode was then
restored in settings.

Earlier image-bearing MiniMax and Kimi attempts hit the existing per-candidate
45-second timeout. The successful run used the unchanged timeout and approval
policy. These service failures are separate from native input acceptance. The
native UI run exercised released input state; sustained held inputs and their
presentation are covered by native fixtures and UI automated tests respectively,
not claimed as a live UI observation.

After the output-overflow fix, the universal helper build, strict signature
verification, Swift checks and seven protocol tests passed again (one opt-in
Locked Use test skipped). A final canonical Electron cold start loaded the new
helper and retained background mode, with no active input session or application
grant. The task-owned fixture applications and diagnostic processes were stopped;
both temporary model-provider credentials were removed through the official API.

After the keyboard and window-identity follow-ups, the separate universal build,
strict signature verification, Swift structural checks and seven protocol cases
passed again (one opt-in case skipped). The final canonical development launch
started Electron, its Rust sidecar and the newly built helper through the
authenticated control pipe. The unlocked native UI retained background mode,
displayed current system permissions, and showed no active operation or application
grant. The development launcher builds the host-architecture helper; the universal
check is a separate build. Task-owned test applications, monitors and the
development client were stopped after validation. Diagnostic logs were retained
and disposable fixture bundles removed.

## Repeating the native checks

From `agi-stack/apps/desktop/cua-helper`, the following executable checks use
disposable fixture applications. The physical-input check requires an operator;
the other fixture checks explicitly authorize only their own test windows.

```sh
./test.sh
python3 tests/background_fixture_test.py --allow-own-fixture-input
CUA_FIXTURE_CONTENT=webkit python3 tests/background_fixture_test.py --allow-own-fixture-input --expect-global-button-limit
CUA_FIXTURE_CONTENT=electron python3 tests/background_fixture_test.py --allow-own-fixture-input --expect-global-button-limit
CUA_FIXTURE_SCREEN_INDEX=1 python3 tests/background_fixture_test.py --allow-own-fixture-input --fault-target-exit
python3 tests/background_focus_fixture_test.py --allow-own-fixture-input
python3 tests/native_fixture_test.py --allow-own-fixture-input
python3 tests/physical_input_test.py --allow-own-fixture-input
python3 tests/keyboard_input_fixture_test.py --allow-own-fixture-input --case layout
CUA_FIXTURE_CONTENT=webkit python3 tests/keyboard_input_fixture_test.py --allow-own-fixture-input --case layout
CUA_FIXTURE_CONTENT=electron python3 tests/keyboard_input_fixture_test.py --allow-own-fixture-input --case layout
python3 tests/keyboard_input_fixture_test.py --allow-own-fixture-input --case ime --human-ime --ime-source com.sogou.inputmethod.sogou.pinyin
python3 tests/native_compatibility_fixture_test.py --allow-own-fixture-input --scenario space
python3 tests/native_compatibility_fixture_test.py --allow-own-fixture-input --scenario lock
```

Native client acceptance still starts from the repository root with
`make -C agi-stack run-desktop`. A renderer-only development server cannot
validate the private Electron/sidecar/helper chain.
