"""Exercise the same signed composer in equally wide Web and Electron panels."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from .test_original_agent_web_layout import workbench

pytestmark = pytest.mark.integration


def panel_geometry(frame):
    chat = frame.get_by_role("main", name=re.compile("^(Chat|聊天)$"))
    draft = chat.get_by_test_id("chat-input")
    expect(draft).to_be_visible(timeout=90000)
    inbox = chat.get_by_role("button", name=re.compile("Open Activity|打开动态"))
    expect(inbox).to_be_visible()
    return {
        "width": chat.bounding_box()["width"],
        "draft_width": draft.bounding_box()["width"],
        "label": inbox.get_by_text(re.compile("Activity|动态")).is_visible(),
        "overflow": chat.evaluate("e => e.scrollWidth - e.clientWidth"),
    }


def exercise_narrow_panel(guest):
    skip = guest.get_by_role("button", name=re.compile("^(Skip tour|跳过引导)$"))
    if skip.is_visible():
        skip.click()
    draft = guest.get_by_test_id("chat-input")
    draft.fill("narrow panel draft")
    modes = guest.locator('[data-tour="layout-selector"]')
    modes.get_by_role("button", name=re.compile("^(Task mode|任务模式)$")).click()
    modes.get_by_role("button", name=re.compile("^(Chat mode|聊天模式)$")).click()
    expect(draft).to_have_value("narrow panel draft")


def test_shared_composer_adapts_to_its_panel():
    cdp = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    owner_file = os.getenv("MEMSTACK_QA_AGENT_LAYOUT_OWNER")
    if not cdp or not owner_file:
        pytest.skip("requires the installed Web page and a signed-in native Electron window")
    owner = json.loads(Path(owner_file).read_bytes())
    with sync_playwright() as pw:
        native = pw.chromium.connect_over_cdp(cdp).contexts[0].pages[0]
        native.evaluate("() => { location.hash = '/agent/chat'; }")
        guest = native.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        browser = pw.chromium.launch()
        with workbench(browser, owner, True, "en-US", "light") as (web, shared):
            for width in (1520, 1150, 760):
                native.set_viewport_size({"width": width, "height": 900})
                actual = panel_geometry(guest)
                web.set_viewport_size({"width": width, "height": 900})
                initial_width = panel_geometry(shared)["width"]
                web.set_viewport_size(
                    {"width": width + int(actual["width"] - initial_width), "height": 900}
                )
                compared = panel_geometry(shared)
                assert actual["width"] == compared["width"], (actual, compared)
                assert actual["draft_width"] == pytest.approx(compared["draft_width"], abs=1)
                assert actual["label"] == compared["label"]
                assert actual["overflow"] == compared["overflow"] == 0
                print(f"Panel {actual['width']}px: {actual}")
            for frame in (guest, shared):
                exercise_narrow_panel(frame)
        browser.close()
