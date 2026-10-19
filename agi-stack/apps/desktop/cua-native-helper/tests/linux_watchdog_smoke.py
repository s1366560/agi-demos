#!/usr/bin/env python3
"""Real Xvfb/XI2 hard-fault acceptance. No host display or physical input is used."""

import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import ClassVar

import linux_native_smoke as smoke


class State:
    def __init__(self):
        self.x = ctypes.CDLL("libX11.so.6")
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XQueryPointer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.display = self.x.XOpenDisplay(None)
        self.code = self.x.XKeysymToKeycode(self.display, 0xFFE1)

    def native_source(self):
        class DeviceInfo(ctypes.Structure):
            _fields_: ClassVar[list[tuple[str, type]]] = [
                ("id", ctypes.c_int),
                ("name", ctypes.c_char_p),
                ("use", ctypes.c_int),
                ("attachment", ctypes.c_int),
                ("enabled", ctypes.c_int),
                ("classes_len", ctypes.c_int),
                ("classes", ctypes.c_void_p),
            ]

        xi = ctypes.CDLL("libXi.so.6")
        xi.XIQueryDevice.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        xi.XIQueryDevice.restype = ctypes.POINTER(DeviceInfo)
        xi.XIFreeDeviceInfo.argtypes = [ctypes.POINTER(DeviceInfo)]
        count = ctypes.c_int()
        devices = xi.XIQueryDevice(self.display, 0, ctypes.byref(count))
        try:
            # This is native protocol device metadata in the isolated Xvfb fixture.
            candidates = [
                devices[index].id
                for index in range(count.value)
                if devices[index].use == 4
                and devices[index].enabled
                and devices[index].name == b"Xvfb keyboard"
            ]
            assert len(candidates) == 1, candidates
            source = candidates[0]
        finally:
            xi.XIFreeDeviceInfo(devices)
        xi.XOpenDevice.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xi.XOpenDevice.restype = ctypes.c_void_p
        device = xi.XOpenDevice(self.display, source)
        assert device
        xtst = ctypes.CDLL("libXtst.so.6")
        xtst.XTestFakeDeviceKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]

        def inject(down):
            assert xtst.XTestFakeDeviceKeyEvent(
                self.display, device, self.code, int(down), None, 0, 0
            )
            self.x.XSync(self.display, 0)

        return source, inject

    def break_worker_driver(self, pid):
        class Tree(ctypes.Structure):
            _fields_: ClassVar[list[tuple[str, type]]] = [
                ("data", ctypes.c_int),
                ("request", ctypes.c_int),
                ("first", ctypes.c_int),
                ("all", ctypes.c_int),
            ]

        self.x.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x.XInternAtom.restype = ctypes.c_ulong
        self.x.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.x.XFree.argtypes = [ctypes.c_void_p]
        self.x.XKillClient.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        root, parent = ctypes.c_ulong(), ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        assert self.x.XQueryTree(
            self.display,
            self.x.XDefaultRootWindow(self.display),
            ctypes.byref(root),
            ctypes.byref(parent),
            ctypes.byref(children),
            ctypes.byref(count),
        )
        atom = self.x.XInternAtom(self.display, b"_NET_WM_PID", False)
        matches = []
        try:
            for index in range(count.value):
                actual_type, items, remaining = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
                format_ = ctypes.c_int()
                value = ctypes.POINTER(ctypes.c_ubyte)()
                self.x.XGetWindowProperty(
                    self.display,
                    children[index],
                    atom,
                    0,
                    1,
                    False,
                    6,
                    ctypes.byref(actual_type),
                    ctypes.byref(format_),
                    ctypes.byref(items),
                    ctypes.byref(remaining),
                    ctypes.byref(value),
                )
                if value:
                    if (
                        format_.value == 32
                        and items.value == 1
                        and ctypes.cast(value, ctypes.POINTER(ctypes.c_ulong))[0] == pid
                    ):
                        matches.append(children[index])
                    self.x.XFree(value)
        finally:
            self.x.XFree(children)
        assert len(matches) == 1, matches
        self.x.XKillClient(self.display, matches[0])
        self.x.XSync(self.display, 0)

    def held(self):
        keys = (ctypes.c_ubyte * 32)()
        self.x.XQueryKeymap(self.display, keys)
        root = ctypes.c_ulong()
        child = ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        self.x.XQueryPointer(
            self.display,
            self.x.XDefaultRootWindow(self.display),
            ctypes.byref(root),
            ctypes.byref(child),
            ctypes.byref(rx),
            ctypes.byref(ry),
            ctypes.byref(wx),
            ctypes.byref(wy),
            ctypes.byref(mask),
        )
        return bool(keys[self.code // 8] & (1 << (self.code % 8))), bool(mask.value & (1 << 8))


# Preserve fault ordering and held-input assertions within the same isolated native session.
def exercise(executable, mode):  # noqa: C901, PLR0912, PLR0915
    with tempfile.TemporaryDirectory(prefix="memstack-native-watchdog-") as directory:
        app = subprocess.Popen(
            [sys.executable, smoke.__file__, "--fixture", str(Path(directory) / "value.txt")]
        )
        client = smoke.Client(executable)
        contender = smoke.Client(executable) if "distinct_source" in mode else None
        state = State()
        try:
            for _ in range(40):
                apps = client.call("list_apps", {})["apps"]
                target = next((value for value in apps if value["process_id"] == app.pid), None)
                if target:
                    break
                time.sleep(0.1)
            assert target is not None
            capabilities = client.call("capabilities", {}, bound=False)["capabilities"]
            assert capabilities["key_hold"]["state"] == "available", capabilities
            window = client.call("list_windows", {"app": f"pid:{app.pid}"})["windows"][0]
            params = {
                "app": f"pid:{app.pid}",
                "window_id": window["window_id"],
                "expected_identity_digest": target["identity_digest"],
            }
            client.call("activate_app", params)
            if contender:
                try:
                    contender.call("activate_app", params)
                    raise AssertionError("independent helper acquired an owned native display")
                except AssertionError as error:
                    assert "desktop_busy" in str(error), error

            def act(action):
                observed = client.call("get_app_state", params)
                return client.call(
                    "perform_action",
                    {**params, "snapshot_id": observed["snapshot_id"], "action": action},
                )

            assert state.held() == (False, False)
            try:
                act({"kind": "key_down", "key": "Shift+NoSuchNativeKey"})
                raise AssertionError("unknown native key was accepted")
            except AssertionError as error:
                assert "invalid_params" in str(error), error
            assert state.held() == (False, False), "failed chord retained a partial injected hold"
            act({"kind": "key_down", "key": "Shift"})
            act({"kind": "drag_step", "phase": "begin", "x": 100, "y": 40})
            assert state.held() == (True, True)
            native_source = None
            if "distinct_source" in mode:
                native_source, inject = state.native_source()
                inject(True)
                time.sleep(0.1)
            started = time.monotonic()
            if mode.startswith(("worker_", "guardian_")):
                guardian = int(
                    Path(f"/proc/{client.process.pid}/task/{client.process.pid}/children")
                    .read_text()
                    .split()[0]
                )
                worker = int(
                    Path(f"/proc/{guardian}/task/{guardian}/children").read_text().split()[0]
                )
                assert b"--input-worker" in Path(f"/proc/{worker}/cmdline").read_bytes().split(
                    b"\0"
                )
                if mode == "worker_driver_error":
                    state.break_worker_driver(worker)
                elif mode.startswith("guardian_"):
                    os.kill(
                        guardian, signal.SIGSTOP if mode.endswith("SIGSTOP") else signal.SIGKILL
                    )
                else:
                    os.kill(worker, signal.SIGKILL)
            else:
                client.process.send_signal(signal.SIGSTOP if mode == "SIGSTOP" else signal.SIGKILL)
            if native_source is not None:
                time.sleep(0.2)
                assert state.held() == (True, False), state.held()
                try:
                    contender.call("activate_app", params)
                    raise AssertionError("device lease ended before owned input released")
                except AssertionError as error:
                    assert "desktop_busy" in str(error), error
                inject(False)
            for _ in range(160):
                if state.held() == (False, False):
                    break
                time.sleep(0.05)
            assert state.held() == (False, False), (mode, state.held())
            client.process.wait(timeout=2)
            assert client.process.poll() is not None, (
                "expired or unsafe helper can still resume input"
            )
            for _ in range(40):
                if not client.root.exists():
                    break
                time.sleep(0.05)
            assert not client.root.exists(), "private root was not cleaned by the guardian"
            elapsed = time.monotonic() - started
            if contender:
                for _ in range(40):
                    try:
                        contender.call("activate_app", params)
                        break
                    except AssertionError as error:
                        assert "desktop_busy" in str(error), error
                        time.sleep(0.05)
                else:
                    raise AssertionError("device lease did not release after native cleanup")
            if not mode.endswith("SIGSTOP"):
                assert elapsed < 2, elapsed
            else:
                assert 4 <= elapsed < 8, elapsed
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "platform": "isolated_linux_x11",
                        "fault": mode,
                        "key_and_mouse_before_fault": [True, True],
                        "key_and_mouse_after_guard_cleanup": list(state.held()),
                        "cleanup_seconds": round(elapsed, 3),
                        "simulated_native_source_id": native_source,
                        "independent_helper_lease_checked": contender is not None,
                        "physical_hardware_tested": False,
                    }
                )
            )
        finally:
            if client.process.poll() is None:
                client.process.send_signal(signal.SIGCONT)
                client.process.kill()
            client.process.wait(timeout=5)
            if contender:
                contender.call("end_session", {})
                contender.process.stdin.close()
                contender.process.wait(timeout=5)
                shutil.rmtree(contender.root, ignore_errors=True)
            # Only the fixture display receives this emergency cleanup after an assertion failure.
            subprocess.run(["xdotool", "keyup", "Shift", "mouseup", "1"], check=True)
            shutil.rmtree(client.root, ignore_errors=True)
            app.terminate()
            app.wait(timeout=5)


if __name__ == "__main__":
    if sys.argv[1] == "--inside":
        manager = subprocess.Popen(
            ["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for mode in (
                "SIGKILL",
                "SIGSTOP",
                "SIGKILL_distinct_source",
                "worker_SIGKILL",
                "worker_driver_error",
                "worker_SIGKILL_distinct_source",
                "guardian_SIGKILL",
                "guardian_SIGKILL_distinct_source",
                "guardian_SIGSTOP",
            ):
                exercise(sys.argv[2], mode)
        finally:
            manager.terminate()
            manager.wait(timeout=5)
    else:
        subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1024x768x24",
                "dbus-run-session",
                sys.executable,
                __file__,
                "--inside",
                os.path.abspath(sys.argv[1]),
            ],
            check=True,
        )
