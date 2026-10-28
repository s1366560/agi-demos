"""Opt-in native non-US layout and active IME isolation acceptance.

The test temporarily selects a real installed input source and restores it in
finally. A separately tagged native key sender composes only in the owned
foreground Guard; the helper sends background input only to its owned Target.
No AX value assignment, clipboard paste, or manufactured marked text is used.
"""

import argparse
import json
import os
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path

from background_fixture_test import ROOT, BackgroundFixture, rows, until


class InputSourceController:
    def __init__(self, binary, guard_pid, identifier):
        self.process = subprocess.Popen(
            [str(binary), "--allow-own-fixture-input", str(guard_pid), "--source", identifier],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            self.ready = self.read()
            assert self.ready.get("ready"), self.ready
            assert self.ready["current"]["input_source"]["id"] == identifier, self.ready
        except Exception:
            if self.process.poll() is None:
                output, error = self.process.communicate('{"operation":"restore"}\n', timeout=5)
                print("INPUT_SOURCE_SETUP_RESTORE", output, error, flush=True)
            raise

    def read(self):
        assert select.select([self.process.stdout], [], [], 10)[0], "input source probe timed out"
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read()
        return json.loads(line)

    def command(self, operation, **values):
        self.process.stdin.write(json.dumps({"operation": operation, **values}) + "\n")
        self.process.stdin.flush()
        return self.read()

    def keys(self, codes, flags=0):
        result = self.command("keys", key_codes=codes, flags=flags)
        assert result.get("sent") == len(codes), result
        return result

    def close(self):
        if self.process.poll() is None:
            result = self.command("restore")
            self.process.wait(timeout=5)
            assert result["restored"] and result["disabled_temporary_source"], result
            assert result["current"]["input_source"]["id"] == self.ready["original"]["id"], result
            print("INPUT_SOURCE_RESTORED", json.dumps(result, ensure_ascii=False), flush=True)


class KeyboardFixture(BackgroundFixture):
    def launch(self, name, identifier, *, background):
        # Keep the Guard a native NSTextField even when the Target is WebKit.
        original = os.environ.get("CUA_FIXTURE_CONTENT")
        if not background:
            os.environ["CUA_FIXTURE_CONTENT"] = "appkit"
        try:
            return super().launch(name, identifier, background=background)
        finally:
            if original is None:
                os.environ.pop("CUA_FIXTURE_CONTENT", None)
            else:
                os.environ["CUA_FIXTURE_CONTENT"] = original

    def clear_target(self):
        state = until(
            self.observe, lambda value: re.search(r"\[(\d+)\] AXTextField", value["text"])
        )
        element = int(re.search(r"\[(\d+)\] AXTextField", state["text"])[1])
        self.action({"kind": "click", "element_index": element}, state=state)
        self.action({"kind": "press_key", "key": "super+a"})
        self.action({"kind": "press_key", "key": "BackSpace"})

    def expect_target(self, expected):
        return until(
            self.observe,
            lambda value: any(
                "AXTextField" in line and f'value="{expected}"' in line
                for line in value["text"].splitlines()
            ),
        )

    def reset_isolation_baseline(self):
        # An IME can commit on Space key-down, before the operator releases it.
        self.baseline = until(
            self.system_state, lambda value: not value["held_key_codes"], timeout=10
        )
        assert self.baseline["frontmost_pid"] == self.guard.pid, self.baseline
        self.guard_offset = len(rows(self.logs["Foreground Guard"]))
        until(lambda: rows(self.system_log), lambda values: values[-1] == self.baseline)
        self.system_offset = len(rows(self.system_log)) - 1

    def keyboard_capabilities(self):
        return self.channel.request("capabilities", {})["result"]["keyboard_input"]

    def human_instruction(self, stage, message):
        self.instruction_paths["Foreground Guard"].write_text(message)
        print(
            stage,
            json.dumps({"guard_pid": self.guard.pid, "instruction": message}, ensure_ascii=False),
            flush=True,
        )

    def non_us_layout(self, binary):
        self.clear_target()
        controller = InputSourceController(binary, self.guard.pid, "com.apple.keylayout.French")
        try:
            capabilities = self.keyboard_capabilities()
            assert capabilities["key_names"] == "ansi_us_physical_positions", capabilities
            assert capabilities["keyboard_layout"] == "com.apple.keylayout.French", capabilities
            assert capabilities["input_source"] == "com.apple.keylayout.French", capabilities
            before = len(rows(self.logs["Background Target"]))
            self.action({"kind": "press_key", "key": "a"})
            self.expect_target("q")
            self.action({"kind": "key_down", "key": "q"})
            self.action({"kind": "key_up", "key": "q"})
            self.expect_target("qa")
            self.action({"kind": "press_key", "key": "shift+a"})
            self.expect_target("qaQ")
            self.action({"kind": "type_text", "text": " 中文 é 😀"})
            self.expect_target("qaQ 中文 é 😀")
            keys = [v for v in rows(self.logs["Background Target"])[before:] if v["type"] == 10]
            if self.content != "electron":
                assert [v["key_code"] for v in keys[:3]] == [0, 12, 0], keys
                assert [v["characters"] for v in keys[:3]] == ["q", "a", "Q"], keys
            self.assert_isolated()
            print("NATIVE_FRENCH_LAYOUT_OK", json.dumps(capabilities), flush=True)
        finally:
            controller.close()

    def active_ime(self, binary, identifier, *, human=False, timeout=180):
        controller = InputSourceController(binary, self.guard.pid, identifier)
        try:
            # Allow the Guard's normal run loop to activate the selected IMK
            # client before starting external input; selection itself is async.
            time.sleep(1)
            # The Guard's normal key events are interpreted by the real IME.
            # Command+A/Delete clear only its disposable field.
            controller.keys([0], flags=1 << 20)
            controller.keys([51])
            log = self.composition_logs["Foreground Guard"]
            before = len(rows(log))
            physical_offset = len(rows(self.logs["Foreground Guard"]))
            if human:
                self.human_instruction(
                    "NATIVE_IME_COMPOSE_READY",
                    "请用中文输入 ni，保持候选词。停留在此窗口，等待这里的下一步提示。",
                )
            else:
                controller.keys([45, 34])  # ANSI N, I: start the phonetic composition.
            if human:
                until(
                    lambda: rows(self.logs["Foreground Guard"])[physical_offset:],
                    lambda values: any(
                        value.get("source_pid") == 0
                        and value["type"] == 11
                        and value.get("key_code") == 34
                        for value in values
                    ),
                    timeout=timeout,
                )
            composing = until(
                lambda: rows(log)[before:],
                lambda values: values and values[-1]["has_marked_text"],
                timeout=timeout if human else 5,
            )[-1]
            assert composing["input_source_id"] == identifier, composing
            assert composing["marked_length"] > 0, composing
            if human:
                assert any(
                    value.get("source_pid") == 0 and value["type"] == 10
                    for value in rows(self.logs["Foreground Guard"])[physical_offset:]
                ), "physical key input was not observed"
                self.instruction_paths["Foreground Guard"].write_text(
                    "正在验证后台输入。请暂时保持键盘、鼠标不动，不切换窗口。"
                )
            self.reset_isolation_baseline()
            unchanged = len(rows(log))
            self.clear_target()
            self.action({"kind": "type_text", "text": "后台保留组合 😀"})
            self.expect_target("后台保留组合 😀")
            self.action({"kind": "press_key", "key": "left"})
            self.action({"kind": "key_down", "key": "shift"})
            self.action({"kind": "key_up", "key": "shift"})
            self.assert_isolated()
            assert len(rows(log)) == unchanged, rows(log)[unchanged:]
            continuation = len(rows(log))
            if human:
                self.human_instruction(
                    "NATIVE_IME_COMMIT_READY",
                    "后台隔离已通过。继续输入 hao，再按空格提交“你好”，然后等待完成。",
                )
            else:
                controller.keys([4, 0, 31])  # H, A, O: continue the same active composition.
                until(
                    lambda: rows(log)[continuation:],
                    lambda values: values
                    and values[-1]["has_marked_text"]
                    and values[-1]["marked_length"] > composing["marked_length"],
                )
                controller.keys([49])
            completed = until(
                lambda: rows(log)[continuation:],
                lambda values: values
                and not values[-1]["has_marked_text"]
                and values[-1]["text"] == "你好",
                timeout=timeout if human else 5,
            )
            continued = next(
                value
                for value in completed
                if value["has_marked_text"] and value["marked_length"] > composing["marked_length"]
            )
            committed = completed[-1]
            assert committed["text"] == "你好", committed
            self.reset_isolation_baseline()
            self.assert_isolated()
            print(
                "NATIVE_ACTIVE_IME_ISOLATION_OK",
                json.dumps(
                    {
                        "guard_input": "physical" if human else "external_native_simulation",
                        "composing": composing,
                        "continued": continued,
                        "committed": committed,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if human:
                self.instruction_paths["Foreground Guard"].write_text(
                    "测试通过，已提交“你好”。窗口即将关闭，现在可以返回 Codex。"
                )
                time.sleep(3)
        finally:
            controller.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-own-fixture-input", action="store_true", required=True)
    parser.add_argument("--case", choices=("layout", "ime", "all"), default="all")
    parser.add_argument("--ime-source", default="com.apple.inputmethod.SCIM.ITABC")
    parser.add_argument(
        "--human-ime",
        action="store_true",
        help="Wait for real physical n/i, then h/a/o/Space in the owned Guard",
    )
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="memstack-keyboard-", dir=os.environ.get("TMPDIR")
    ) as path:
        directory = Path(path)
        binary = directory / "keyboard-input-probe"
        subprocess.run(
            [
                "swiftc",
                "-parse-as-library",
                str(ROOT / "tests/KeyboardInputProbe.swift"),
                "-o",
                str(binary),
            ],
            check=True,
        )
        fixture = KeyboardFixture(directory)
        try:
            fixture.setup()
            if args.case in ("layout", "all"):
                fixture.non_us_layout(binary)
            if args.case in ("ime", "all"):
                fixture.active_ime(
                    binary, args.ime_source, human=args.human_ime, timeout=args.timeout
                )
            print("NATIVE_KEYBOARD_FIXTURE_OK", flush=True)
        except Exception:
            if fixture.channel.process.poll() is not None:
                print(
                    "HELPER_EXIT",
                    fixture.channel.process.returncode,
                    fixture.channel.process.stderr.read().decode(errors="replace"),
                    flush=True,
                )
            for name, log in fixture.composition_logs.items():
                print(
                    name, "COMPOSITION", json.dumps(rows(log)[-15:], ensure_ascii=False), flush=True
                )
            for name, log in fixture.logs.items():
                print(name, "EVENTS", json.dumps(rows(log)[-15:], ensure_ascii=False), flush=True)
            raise
        finally:
            fixture.close()


if __name__ == "__main__":
    main()
