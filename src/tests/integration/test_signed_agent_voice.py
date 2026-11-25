"""Installed Web composer and trusted host microphone flow using Chromium's synthetic device."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.test_original_agent_web_layout import (
    conversation,
    owner,
    workbench,
)

pytestmark = pytest.mark.integration
__all__ = ["conversation", "owner"]


def config_mode(frame):
    config = json.loads(frame)
    assert config.get("package_ticket")
    return config["mode"]


def test_installed_voice_consent_dictation_call_and_close(owner, conversation):
    with (
        sync_playwright() as pw,
        pw.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        ) as browser,
        workbench(browser, owner, True, "en-US", "light", conversation) as (page, guest),
    ):
        chat = guest.get_by_role("main", name="Chat", exact=True)
        expect(chat.get_by_title("Composer menu integration", exact=True)).to_be_visible(
            timeout=90000
        )
        connections = []
        audio_modes = []

        def connect(socket):
            assert conversation in socket.url and "package_session=1" in socket.url
            connections.append(socket)
            mode = ""

            def message(frame):
                nonlocal mode
                if isinstance(frame, str):
                    mode = config_mode(frame)
                elif isinstance(frame, bytes) and mode not in audio_modes:
                    assert len(frame) > 0
                    audio_modes.append(mode)
                    socket.send(json.dumps({"type": "asr_final", "text": "voice fixture"}))
                    if mode == "voice":
                        socket.send(json.dumps({"type": "agent_complete", "content": "call reply"}))

            socket.on_message(message)

        page.route_web_socket(re.compile("/api/v1/voice/chat"), connect)

        def action(label):
            chat.get_by_title("Add", exact=True).click()
            chat.get_by_role("menuitem", name=label, exact=True).click()

        page.reload()
        expect(chat.get_by_title("Composer menu integration", exact=True)).to_be_visible(
            timeout=90000
        )
        draft = chat.get_by_test_id("chat-input")
        draft.fill("before ")
        action("Voice input")
        dialog = page.get_by_role("dialog", name="Microphone permission")
        expect(dialog).to_contain_text(conversation, timeout=90000)
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_have_count(0)
        assert not connections
        expect(draft).to_have_value("before ")
        action("Voice input")
        dialog.get_by_role("button", name="Allow once").click(timeout=90000)
        expect(draft).to_have_value("before voice fixture", timeout=60000)
        action("Stop voice input")
        action("Start voice call")
        dialog.get_by_role("button", name="Allow once").click(timeout=90000)
        expect(guest.get_by_text("call reply", exact=True)).to_be_visible(timeout=60000)
        guest.get_by_role("button", name="Mute", exact=True).click()
        expect(guest.get_by_role("button", name="Unmute", exact=True)).to_be_visible()
        guest.get_by_role("button", name="Minimize voice call panel").click()
        guest.get_by_role("button", name="Expand voice call panel").click()
        guest.get_by_role("button", name="End call", exact=True).last.click()
        expect(guest.get_by_text("call reply", exact=True)).to_have_count(0)
        assert audio_modes == ["dictation", "voice"]


def test_installed_native_call_panel_requests_host_permission(owner, conversation):
    from urllib.parse import urlencode

    cdp = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    if not cdp:
        pytest.skip("requires the fixed native client")
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        page = browser.contexts[0].pages[0]
        scope = page.locator(".package-market-scope select")
        if scope.is_visible():
            scope.select_option("project")
        path = f"/tenant/{owner['tenant_id']}/agent-workspace/{conversation}?" + urlencode(
            {"projectId": owner["project_id"]}
        )
        page.evaluate("path => {location.hash=path}", path)
        page.reload()
        guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(guest.get_by_title("Composer menu integration", exact=True)).to_be_visible(
            timeout=90000
        )
        chat = guest.get_by_role("main", name=re.compile("^(Chat|聊天)$"))
        chat.get_by_title(re.compile("^(Add|添加)$")).click()
        chat.get_by_role(
            "menuitem", name=re.compile("Start voice call|开始语音通话|发起语音通话")
        ).click()
        dialog = page.get_by_role("dialog", name=re.compile("Microphone permission|麦克风权限"))
        expect(dialog).to_contain_text(conversation, timeout=15000)
        # Explicit denial exercises the real native host without accessing a physical microphone.
        dialog.get_by_role("button", name=re.compile("Cancel|取消")).click()
        expect(dialog).to_have_count(0)
        expect(guest.get_by_role("button", name=re.compile("End call|结束通话"))).to_have_count(0)


def assert_tracks_ended(page, count):
    from time import monotonic

    deadline = monotonic() + 15
    while monotonic() < deadline:
        states = page.evaluate("() => window.__testVoiceTracks.map(track=>track.readyState)")
        if states == ["ended"] * count:
            return
        page.wait_for_timeout(100)
    pytest.fail(f"Expected {count} ended synthetic microphone tracks, observed {states}")


def change_installation(api, scope, action):
    from src.tests.integration.marketplace_browser import business_release

    market = "/platform-plugins/v2/optional-business"
    info = api.get(
        market + "/npm/detail",
        params={
            **scope,
            "plugin_id": "memstack-agent",
            "package_name": "@memstack/agent",
            "version": business_release("agent"),
        },
    )
    info.raise_for_status()
    result = api.post(
        market + "/memstack-agent/" + action,
        json={**scope, "expected_revision": info.json()["desired_revision"]},
    )
    result.raise_for_status()


@pytest.mark.skipif(
    not os.getenv("MEMSTACK_QA_NATIVE_VOICE_ARTIFACTS"), reason="requires fixed native artifacts"
)
def test_native_synthetic_audio_and_project_revocation(owner, conversation, monkeypatch, tmp_path):
    import httpx

    from scripts.dev import verify_six_workbenches as lifecycle
    from src.tests.integration.voice_fixture import DEV_API, SpeechFixture

    # Disabling the active package is part of the scenario. Only use its disposable project.
    assert owner.get("project_name") == "Shared Agent voice QA"
    scope = {k: owner[k] for k in ("tenant_id", "project_id")}
    fixture = SpeechFixture(scope["project_id"], conversation)
    artifacts = Path(os.environ["MEMSTACK_QA_NATIVE_VOICE_ARTIFACTS"]).resolve()
    monkeypatch.setenv(
        "MAKEFLAGS",
        r"DESKTOP_PROFILE_ENTRY=.\ --use-fake-device-for-media-stream\ --enable-automation",
    )
    with fixture.running() as origin, httpx.Client(base_url=DEV_API + "/api/v1", timeout=30) as api:
        login = api.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        api.headers["authorization"] = "Bearer " + login.json()["access_token"]
        monkeypatch.setattr(lifecycle, "API", origin)
        with (
            lifecycle.native_window(artifacts, tmp_path / "electron.log", owner, True) as cdp,
            sync_playwright() as pw,
        ):
            browser = pw.chromium.connect_over_cdp(cdp)
            args = browser.new_browser_cdp_session().send("Browser.getBrowserCommandLine")[
                "arguments"
            ]
            assert "--use-fake-device-for-media-stream" in args
            page = browser.contexts[0].pages[0]
            page.locator(".package-market-scope select").select_option("project")
            page.add_init_script("""if (self===top) {
              window.__testVoiceTracks=[];
              const capture=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
              navigator.mediaDevices.getUserMedia=async (...args)=>{
                const stream=await capture(...args);
                window.__testVoiceTracks.push(...stream.getAudioTracks());
                return stream;
              };
            }""")
            page.evaluate(
                "path=>location.hash=path",
                f"/tenant/{scope['tenant_id']}/agent-workspace/{conversation}?projectId={scope['project_id']}",
            )
            page.reload()
            guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            expect(guest.get_by_title("Composer menu integration", exact=True)).to_be_visible(
                timeout=90000
            )
            chat = guest.get_by_role("main", name=re.compile("^(Chat|聊天)$"))
            draft = chat.get_by_test_id("chat-input")
            draft.fill("before ")

            def action(label):
                chat.get_by_title(re.compile("^(Add|添加)$")).click()
                chat.get_by_role("menuitem", name=re.compile(label)).click()

            def approve():
                # Approve only the in-app dialog. OS permission sheets are never automated.
                page.get_by_role("button", name=re.compile("Allow once|允许本次使用")).click(
                    timeout=90000
                )

            action("^(Voice input|语音输入)$")
            approve()
            expect(draft).to_have_value("before synthetic fixture", timeout=60000)
            action("Stop voice input|停止语音输入")
            assert_tracks_ended(page, 1)
            action("Start voice call|开始语音通话")
            approve()
            expect(guest.get_by_text("native test reply", exact=True)).to_be_visible(timeout=60000)
            change_installation(api, scope, "disable")
            try:
                assert_tracks_ended(page, 2)
                # Tracks are stopped on the trusted renderer; the socket close traverses IPC.
                for _ in range(50):
                    if len(fixture.closed) == 2:
                        break
                    page.wait_for_timeout(100)
                assert fixture.received == fixture.closed == ["dictation", "voice"]
            finally:
                change_installation(api, scope, "enable")
