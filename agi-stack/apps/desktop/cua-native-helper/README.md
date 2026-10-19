# Native computer-use helper

`memstack-cua-native-helper` implements the Windows and Linux backends. The desktop
build stages this binary beside the Rust sidecar as `cua-helper.exe` or `cua-helper`.
The macOS build uses the separate Swift helper. Launch the complete desktop client
from the repository root with `make -C agi-stack run-desktop`.

## Native backends

- Windows: COM MTA UI Automation with exact RuntimeId references, Windows Graphics
  Capture for an exact HWND, SendInput, multi-format Win32 clipboard snapshots,
  WASAPI microphone and loopback recording, AppsFolder identities and native
  ShellExecuteEx PIDL or packaged-app AUMID activation.
- Linux X11: AT-SPI object references, XTest input, exact XComposite window/frame
  pixmap capture, native multi-format clipboard selections including INCR, and GIO
  DesktopAppInfo installed application IDs.
- Linux Wayland: an explicitly approved RemoteDesktop and ScreenCast portal
  session, PipeWire capture, native EIS keyboard/button holds and phased drags,
  portal key/motion notifications, and data-control clipboard transfers. The
  clipboard requires one exact named seat. Missing native interfaces are reported
  as unavailable or unsupported.
- Linux audio: PulseAudio or PipeWire-Pulse devices with GStreamer. Mixed capture
  uses audiomixer and exports one playable stereo 48 kHz, signed 16-bit PCM WAV.
  Windows mixed capture aligns native packet timestamps, resamples and saturates
  samples into the same export format.

Input stops on native lock detection. Windows secure desktop and Linux locked
session control are unsupported. Personal-data connectors use the desktop's
configured provider or MCP adapters on these platforms; this helper reports the
absence of universal native Calendar, Contacts and Messages APIs.

## Transport and ownership

The private stdio channel uses JSON-RPC 2.0 inside bounded four-byte little-endian
frames. IPC version 2 initialization returns a lowercase HMAC-SHA256 proof of the
UTF-8 secret and nonce. This authenticates the owned transport; the sidecar remains
responsible for application and device authorization.

Every session binds device, user, tenant, project, conversation, run and session
IDs. Each call retains that complete context. Capabilities and read-only system
permission status are management probes. Permission requests use a bound settings
session. A global input lease, one-use snapshot ID, exact native window identity,
focus checks and approved executable digest guard actions. Stop, reset and EOF
release held inputs and owned clipboard contents and stop recording. Pause cancels
in-flight native actions before cleanup, clears temporary captures/icons/audio and
keeps a live paused session. Resume requires a fresh observation, without restarting
input or audio. Stop is terminal and cannot be resumed or reset. Cancel is recoverable; timeout
reset cannot bypass a user pause or terminal stop.

Windows and X11 use three instances of the same signed helper: the main backend,
`--input-watchdog` resource guardian, and `--input-worker` injection worker. The
private pipes acknowledge claims before injection. The guardian also keeps a
passive native input mirror. A worker fault fences the main helper and the mirror
releases only owned input; a guardian fault fences the main helper while the
worker performs its own cleanup. Windows marks SendInput and tracks low-level
hooks plus native RawInput device sources; X11 tracks XI2 source devices separately
from XTEST. Physical same-key ownership delays release until that source releases
its key. If native source tracking is unavailable, held input is unavailable.

Every child pins its OS-reported parent, creation identity, and this same native
executable image. A five-second heartbeat expiry terminates that exact parent
before final release, so a suspended backend cannot later resume input or retain
recording handles. Normal EOF allows a 200 ms exit grace period before bounded
termination. Linux uses pidfds and TERM then KILL; Windows pins a process handle
and uses bounded TerminateProcess after the graceful private-pipe interval.

The guardian creates private artifact roots before returning them, keeps their
native directory identities, and removes only those roots on failure. The main
helper retains native inode/file-ID receipts for cleanup if the guardian dies.
Clipboard writes and their complete format baselines live in the guardian. Before
a write, the existing worker acknowledges an in-memory baseline backup. X11 uses
XFixes owner-change, window-destroy and client-close events to prove loss of the
exact writer, followed by a GrabServer ownership check and restore. A new user
owner or explicit clear invalidates that receipt. No old X11 connection is retained,
so killing a writer inside GrabServer releases the server grab. Windows requires a
committed sequence, owner and random native format marker in one OpenClipboard
transaction. If a Windows writer dies before its commit receipt can be confirmed,
the backup leaves the clipboard unchanged because ownership is unknown.

A native cross-process device lease serializes independent desktop profiles:
Windows uses current-session named mutexes with current-user SID DACLs; Linux
uses UID-owned 0600, no-follow advisory flocks inside a 0700 directory. Separate
resource and input leases ensure a surviving guardian or worker prevents another
profile from injecting until owned input has been released. These fixed lock
files are not shared RPC sockets.

Installed application launch accepts only an ID in native inventory, validates
the current registration and executable fingerprint, and returns the actual new
process when it becomes observable. Input requires a fresh observation of that
process. Model-supplied executable paths and command strings are never launch
arguments.

Application icons use native Windows Shell ICONONLY metadata or an exact X11
window's EWMH icon. Linux installed entries use registered GIcon raster resources
inside native XDG icon namespaces. Icons are 64 by 64 owned PNG artifacts returned
by resolve_app/get_app_state, never inline base64 or model vision attachments.
Unavailable native or raster resources include an explicit reason; SVG-only themes
are currently unavailable. Previews reuse the already authorized window screenshot.
App lists include exact native windows and running state. Installed entries are
associated only by exact native AUMID on Windows or a complete literal native
DesktopAppInfo command line on Linux; field-code expansions are left unassociated.
Window modal/type values come directly from UIA or AT-SPI, with unknown fields
omitted. No usage dates or counters are invented.

Linux observations include a public ax_tree bound to the same snapshot/window.
Nodes preserve actual AT-SPI parent indices, native role/name/value/state/action
metadata and bounds. Password values and unknown-role values are suppressed;
private element references remain solely in the helper. Traversal retains the
4096-node, 64-depth, 256 KiB text bounds and reports truncation. The common Host
validates the strict public schema, identity binding and structural limits.

Artifacts use a private session directory and actual encoded dimensions. The
sidecar copies exported files to owner media storage for transcript recovery;
helper temporary files are cleared on pause/stop. X11 clipboard restoration has
native selection-owner lifetime. Wayland portal restore tokens are not persisted:
the current portal session owns the permission and a new session requests native
consent again.

## Build and tests

From `agi-stack`:

```sh
cargo build -p memstack-cua-native-helper
cargo test -p memstack-cua-native-helper
python3 apps/desktop/cua-native-helper/tests/linux_native_smoke.py \
  target/debug/memstack-cua-native-helper
python3 apps/desktop/cua-native-helper/tests/linux_native_smoke.py \
  --without-composite target/debug/memstack-cua-native-helper
python3 apps/desktop/cua-native-helper/tests/linux_watchdog_smoke.py \
  target/debug/memstack-cua-native-helper
python3 apps/desktop/cua-native-helper/tests/linux_resources_smoke.py \
  target/debug/memstack-cua-native-helper
```

The Linux native smoke test creates its own Xvfb desktop, DBus session, GTK
fixtures and temporary XDG application registration. It exercises actual AT-SPI,
capture, native app icons/modal metadata, pause/resume of held input, Unicode input,
held keys, phased drag, clipboard preservation/INCR and
installed application launch with a fresh PID and observation. It does not use
host applications, accounts or audio devices. Unit audio tests generate synthetic
PCM and GStreamer audiotestsrc data.

The capture fixture covers the target with a red window from another application
and confirms the target pixmap still contains its own pixels. Without Composite,
capture reports unavailable and never falls back to a root-display screenshot.
The watchdog fixture sends real SIGKILL and SIGSTOP to the main helper and
guardian, kills the injection worker, and disconnects its exact native X client
to exercise a real driver error. It checks Shift and mouse-button cleanup and
simulates another XI2 source with the Xvfb keyboard device. Independent helpers
verify lease contention until cleanup completes. That simulated-source test is
not a physical-hardware test. The resource fixture checks baseline restoration,
new user copies, explicit clears, and native private-root cleanup on main and
guardian kill/stop. A debug-only isolated fixture acknowledges a real server grab
before killing the guardian, then checks another client's bounded roundtrip and
copy. This fixture entry point is absent from release builds.

Wayland capture is explicitly `authorized_display`: its portal monitor stream is
bound to the granted source node and logical geometry, and the target crop checks
focus and geometry. The portal does not expose an exact application/window
identity, so this backend reports exact-window capture as unavailable. Portal
generation changes invalidate in-flight captures.

Wayland reports `clipboard_crash_recovery=unavailable` because its current
selection protocol does not provide a verified cross-process ownership receipt.
If the clipboard source disappears, release returns `restoration_state=unknown`
with an explicit reason and leaves the selection unchanged. Normal clipboard
availability is independent of this fault-recovery capability.

Linux needs GStreamer 1.22+, GLib/GIO 2.58+, base/good plugins, PipeWire plugin for
Wayland capture, libxkbcommon, AT-SPI and a session DBus. X11 needs Composite 0.2+,
XI2 2.0+ for held input, XTEST 2.2+, XFixes 1.0+ for fault-safe clipboard ownership, xdotool,
xdpyinfo, xprop and xwininfo. Audio enumeration needs pactl and a PulseAudio or
PipeWire-Pulse service. Wayland needs a working compositor portal backend with
RemoteDesktop/ScreenCast and EIS for held input. The native smoke fixture also
needs Xvfb, openbox, GTK3 Python bindings and python3-dbus.

The development host is macOS. Linux tests and native X11 fixtures were executed
in a Linux container. Windows GNU target compilation and linking cover the full
backend and native codecs. Windows UI/hardware and Wayland compositor acceptance
require their respective environments and are not established by cross-compiling.
Wayland uses its existing portal/EIS and selection-offer cleanup; the independent
X11/Windows mirror fault tests do not establish Wayland guardian-fault recovery.
No actual microphone, loopback recording or physical keyboard device was used.

The pinned native discovery dependency and EIS adaptation are MIT-licensed; see
`THIRD_PARTY_NOTICES.md` for source and license details.
