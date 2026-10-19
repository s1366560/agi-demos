# Native menu UI acceptance driver

This independent macOS QA driver operates the real Computer Use menu through Accessibility
and captures its visible pixels with ScreenCaptureKit. It does not call product IPC, grant
permissions, modify application data, or add a production endpoint or release gate.

Launch the desktop normally from the repository root with `make -C agi-stack run-desktop`.
Use a dedicated test workspace and an authorized native fixture. Keep the parent task running
with observations remaining when testing Resume. The OS must already allow Accessibility and
Screen Recording for the invoking host; the driver does not request or bypass those permissions.

Build into your own direct child of `${TMPDIR}`:

```sh
qa_menu_dir=$(mktemp -d "${TMPDIR%/}/memstack-menu-native-driver.XXXXXX")
swiftc -parse-as-library agi-stack/apps/desktop/cua-helper/tests/native_menu_driver.swift \
  -o "$qa_menu_dir/native-menu-driver"
```

Use the actual sidecar-owned helper PID and exact executable path. The `identity` command only
reads process metadata. Copy its `start` value into every subsequent command. The driver checks
the bundle identifier, canonical executable path, PID, and libproc process start time.

```sh
"$qa_menu_dir/native-menu-driver" identity --pid "$qa_helper_pid" --executable "$qa_helper_exe"
"$qa_menu_dir/native-menu-driver" inspect --pid "$qa_helper_pid" --executable "$qa_helper_exe" \
  --start "$qa_helper_start"
```

`inspect` returns only the selected helper's AX roots, paths, roles, exact labels, frames, and
owned window IDs with visibility and layers. Copy observed values; do not guess paths. Paths
are dot-separated child indices, or `.` for a root. The common status root is `extras`; an open
menu can also appear under `application` or `window:N`.

```sh
"$qa_menu_dir/native-menu-driver" capture-status --pid "$qa_helper_pid" \
  --executable "$qa_helper_exe" --start "$qa_helper_start" --root extras --path 0 \
  --expect-role AXMenuBarItem --expect-label 'Memstack Computer Use' \
  --output "$qa_menu_dir/status-before.png"
"$qa_menu_dir/native-menu-driver" press --pid "$qa_helper_pid" --executable "$qa_helper_exe" \
  --start "$qa_helper_start" --root extras --path 0 --expect-role AXMenuBarItem \
  --expect-label 'Memstack Computer Use'
```

**AXPress error `-25204` is an unknown result, not proof that nothing happened.** macOS can open
the real menu before that call times out. The driver returns `action-result-unknown` and does not
retry. Run `inspect` again, inspect the resulting UI pixels and session state, and decide from
that new observation. Never automatically replay the press. Success from AXPress also requires
checking the visible result and the corresponding application state.

After observing an open helper-owned menu window, capture that exact window ID:

```sh
"$qa_menu_dir/native-menu-driver" capture --pid "$qa_helper_pid" --executable "$qa_helper_exe" \
  --start "$qa_helper_start" --window-id "$qa_menu_window_id" --output "$qa_menu_dir/menu-before.png"
```

`capture-status` accepts only the exact helper-owned `AXMenuBarItem` named `Memstack Computer Use`.
Its AX frame must fit one active display and remain unchanged. ScreenCaptureKit samples only that
small frame; no full-display image is saved. Status icons may belong to WindowServer's menu bar,
so their visibility uses the exact AX ownership and active display bounds. Other controls must
overlap a visible helper-owned window. Menu capture allows the real menu's nonzero layer, requires
the selected window to remain visible with unchanged bounds, and saves a PNG plus JSON metadata.
Existing output files are never overwritten. Identity, element, permission, or geometry failures
stop the operation without changing targets or falling back to broader capture.

For acceptance, visually inspect the actual status icon, controlled-app icon, target window
preview, caption and controls. Use freshly observed paths and exact labels to press Pause,
Resume and Stop. Confirm each state in both menu and desktop, confirm new same-window observations
after Resume, and confirm the owned helper/watchdog exit after Stop. UI pixels and resulting
state establish acceptance; a tree, successful compile, or AXPress return value alone does not.

Restore the prior plugin/permission/workspace state and quit only owned test processes. Preserve
requested screenshots and logs; remove only your own disposable test binaries and fixtures.

Non-UI negative tests compile a metadata-only process fixture and validate rejection before any
UI API is used:

```sh
python3 -m unittest discover -s agi-stack/apps/desktop/cua-helper/tests \
  -p native_menu_driver_test.py -v
```
