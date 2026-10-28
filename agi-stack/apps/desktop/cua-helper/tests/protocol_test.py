"""Real helper framing/handshake/lifecycle tests. No UI input, recording, or sends."""

import hashlib
import hmac
import json
import os
import struct
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [
                os.environ.get("MEMSTACK_CUA_NATIVE_TEST_HELPER", str(ROOT / "bin/cua-helper")),
                "--stdio",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.counter = 0
        self.notifications = []
        self.bindings = {}

    def tearDown(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()

    def request(self, method, params, request_id=None):
        self.counter += 1
        if method == "begin_session":
            params = {"input_mode": "foreground", **params}
        if method != "initialize" and "session_id" in params:
            params = {
                **{
                    field: "fixture-" + field
                    for field in (
                        "user_id",
                        "tenant_id",
                        "project_id",
                        "conversation_id",
                        "run_id",
                        "device_id",
                    )
                },
                **self.bindings.get(params["session_id"], {}),
                **params,
            }
        request = {
            "jsonrpc": "2.0",
            "id": self.counter if request_id is None else request_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(request).encode()
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        header = self.process.stdout.read(4)
        self.assertEqual(len(header), 4)
        (length,) = struct.unpack("<I", header)
        self.assertLessEqual(length, 8_388_608)
        result = json.loads(self.process.stdout.read(length))
        while "id" not in result:
            self.assertEqual(result["method"], "native_status")
            self.notifications.append(result["params"])
            header = self.process.stdout.read(4)
            self.assertEqual(len(header), 4)
            (length,) = struct.unpack("<I", header)
            result = json.loads(self.process.stdout.read(length))
        self.assertEqual(result["id"], request["id"])
        body = result.get("result", {})
        if "session_id" in params and body.get("input_generation"):
            self.bindings[params["session_id"]] = {
                key: body[key] for key in ("input_mode", "input_generation")
            }
        return result

    def initialize(self, notifications=False):
        secret = "fixture-secret-not-a-credential-000000000"
        nonce = "fixture-nonce-000000000000000000000000"
        result = self.request(
            "initialize",
            {
                "client_api_version": "MemstackComputerUseIPC-3",
                "secret": secret,
                "nonce": nonce,
                "native_status_notifications": notifications,
            },
            0,
        )["result"]
        self.assertEqual(result["nonce"], nonce)
        self.assertEqual(
            result["proof"], hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        )

    def test_handshake_and_owned_session_cleanup(self):
        denied = self.request("begin_session", {"session_id": "fixture"})
        self.assertEqual(denied["error"]["data"]["kind"], "authentication_required")
        self.initialize()
        started = self.request("begin_session", {"session_id": "fixture"})["result"]
        self.assertEqual(started["session_id"], "fixture")
        directory = Path(started["artifact_root"])
        self.assertTrue(directory.is_dir())
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        second = self.request("begin_session", {"session_id": "other"})["result"]
        self.assertNotEqual(second["artifact_root"], str(directory))
        denied = self.request("stop_session", {"session_id": "fixture", "device_id": "other"})
        self.assertEqual(denied["error"]["data"]["kind"], "session_owner_mismatch")
        self.assertIn("result", self.request("list_apps", {"session_id": "fixture"}))
        artifact = directory / "fixture-temporary-artifact"
        artifact.write_text("temporary")
        self.request("stop_session", {"session_id": "fixture"})
        self.assertFalse(artifact.exists())
        denied = self.request("list_apps", {"session_id": "fixture"})
        self.assertEqual(denied["error"]["data"]["kind"], "user_stopped_session")
        denied = self.request("reset_session", {"session_id": "fixture"})
        self.assertEqual(denied["error"]["data"]["kind"], "user_stopped_session")
        self.request("end_session", {"session_id": "fixture"})
        self.assertFalse(directory.exists())
        missing = self.request("list_apps", {"session_id": "fixture"})
        self.assertEqual(missing["error"]["data"]["kind"], "session_not_found")

    def test_owned_pause_resume_notifications_and_icon_artifact(self):
        self.initialize(notifications=True)
        base = {"session_id": "presentation-fixture"}
        directory = Path(self.request("begin_session", base)["result"]["artifact_root"])
        resolved = self.request("resolve_app", {**base, "app": "com.apple.TextEdit"})["result"]
        icon = resolved["app_icon"]
        from urllib.parse import unquote, urlparse

        path = Path(unquote(urlparse(icon["url"]).path))
        self.assertEqual(path.parent, directory)
        self.assertEqual(icon["kind"], "app_icon")
        self.assertEqual((icon["width"], icon["height"]), (64, 64))
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotIn("base64", json.dumps(resolved))
        self.request("pause_session", base)
        self.assertEqual(self.notifications[-1]["phase"], "paused")
        self.assertEqual(self.notifications[-1]["context"]["session_id"], base["session_id"])
        self.assertFalse(path.exists(), "pause must clear temporary artifacts")
        self.assertEqual(
            self.request("list_apps", base)["error"]["data"]["kind"], "user_stopped_session"
        )
        self.assertTrue(self.request("resume_session", base)["result"]["requires_observation"])
        self.assertEqual(self.notifications[-1]["phase"], "idle")
        self.assertIn("result", self.request("list_apps", base))
        self.request("stop_session", base)
        self.assertIn("error", self.request("resume_session", base), "stop is terminal for resume")
        self.request("end_session", base)

    def test_cancel_reset_is_recoverable_but_pause_and_stop_are_not(self):
        self.initialize()
        base = {"session_id": "cancel-recovery"}
        self.request("begin_session", base)
        self.request("cancel", base)
        self.assertIn("result", self.request("reset_session", base))
        self.assertIn("result", self.request("list_apps", base))
        self.request("pause_session", base)
        self.assertEqual(
            self.request("reset_session", base)["error"]["data"]["kind"], "user_paused_session"
        )
        self.assertTrue(self.request("resume_session", base)["result"]["requires_observation"])
        self.request("stop_session", base)
        self.assertEqual(
            self.request("reset_session", base)["error"]["data"]["kind"], "user_stopped_session"
        )
        self.request("end_session", base)
        fresh = {"session_id": "fresh-after-stop"}
        self.request("begin_session", fresh)
        self.assertIn("result", self.request("reset_session", fresh))
        self.request("end_session", fresh)

    def test_native_locked_desktop_rejects_gui_before_target_resolution(self):
        self.initialize()
        if not self.request("capabilities", {})["result"]["screen_locked"]:
            self.skipTest("native lock bool is false; no lock operation performed")
        base = {"session_id": "locked-gui"}
        self.request("begin_session", base)
        for method in (
            "get_app_state",
            "list_windows",
            "activate_app",
            "launch_app",
            "perform_action",
        ):
            result = self.request(method, {**base, "app": "no-such-app"})
            self.assertEqual(result["error"]["data"]["kind"], "screen_locked")
        self.request("end_session", base)

    def test_input_binding_rejects_mode_changes_and_old_generations(self):
        self.initialize()
        base = {"session_id": "input-binding"}
        started = self.request("begin_session", base)["result"]
        self.assertEqual(started["input_mode"], "foreground")
        self.assertTrue(started["input_generation"])
        for changed in (
            {"input_mode": "background"},
            {"input_generation": "old-generation"},
        ):
            response = self.request("list_apps", {**base, **changed})
            self.assertEqual(response["error"]["data"]["kind"], "stale_input_generation")
        self.request("pause_session", base)
        resumed = self.request("resume_session", base)["result"]
        self.assertNotEqual(resumed["input_generation"], started["input_generation"])
        rejected = self.request(
            "list_apps", {**base, "input_generation": started["input_generation"]}
        )
        self.assertEqual(rejected["error"]["data"]["kind"], "stale_input_generation")
        self.assertIn("result", self.request("list_apps", base))
        self.request("end_session", base)

    def test_host_can_disable_background_without_implicit_foreground_fallback(self):
        from unittest.mock import patch

        from native_fixture_test import Channel

        with patch.dict(os.environ, {"MEMSTACK_CUA_DISABLE_BACKGROUND_INPUT": "1"}):
            channel = Channel()
        try:
            support = channel.request("capabilities", {})["result"]["input_support"]
            self.assertEqual(
                support["background"],
                {
                    "supported": False,
                    "reason": "background_input_disabled",
                    "global_button_state_emulation": False,
                    "global_activation_suppression": False,
                    "drag_button_state": "event_owned_only",
                },
            )
            denied = channel.request(
                "begin_session", {"session_id": "disabled-background", "input_mode": "background"}
            )
            self.assertEqual(denied["error"]["data"]["kind"], "background_input_unavailable")
            self.assertIn(
                "result",
                channel.request(
                    "begin_session",
                    {"session_id": "explicit-foreground", "input_mode": "foreground"},
                ),
            )
        finally:
            channel.close()

    def test_version_and_request_envelope(self):
        failed = self.request(
            "initialize",
            {
                "client_api_version": "old",
                "secret": "x" * 32,
                "nonce": "x" * 32,
            },
            0,
        )
        self.assertEqual(failed["error"]["data"]["kind"], "incompatible_client_version")
        self.initialize()
        failed = self.request(
            "initialize",
            {
                "client_api_version": "MemstackComputerUseIPC-3",
                "secret": "x" * 32,
                "nonce": "x" * 32,
            },
            0,
        )
        self.assertIn("error", failed)

    def test_closed_audio_session_is_queryable_but_owner_bound(self):
        self.initialize()
        base = {"session_id": "closed-audio"}
        self.request("begin_session", base)
        self.request("end_session", base)
        self.assertEqual(self.request("audio_status", base)["result"]["recordings"], [])
        self.assertEqual(
            self.request("audio_status", {**base, "device_id": "foreign"})["error"]["data"]["kind"],
            "session_owner_mismatch",
        )
        self.assertEqual(
            self.request("audio_ack", {**base, "recording_id": "unknown"})["error"]["data"]["kind"],
            "recording_not_found",
        )
        self.assertEqual(
            self.request("audio_stop", {**base, "end_reason": "unknown"})["error"]["data"]["kind"],
            "invalid_params",
        )
        self.request("begin_session", base)
        self.assertIn("result", self.request("list_apps", base))
        self.request("end_session", base)


if __name__ == "__main__":
    unittest.main()
