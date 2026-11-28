"""Compare the live compatibility and installed workbench shells with identical browser settings."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from .workbench_language import workbench_language

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MEMSTACK_QA_LAYOUT_OWNER"),
        reason="requires both local Web hosts and an isolated QA account",
    ),
]


def exercise_shell_controls(page, states, sidebar, main, header):
    splitter = sidebar.get_by_role("separator").first
    box = splitter.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 48, y, steps=8)
    page.mouse.up()
    assert sidebar.bounding_box()["width"] > states[0][2]["width"]
    states.append([element.bounding_box() for element in (main, header, sidebar)])
    toggle = header.locator("button:visible").first
    toggle.click()
    expect(sidebar).to_have_attribute("aria-hidden", "true")
    toggle.click()
    expect(sidebar).not_to_have_attribute("aria-hidden", "true")
    page.keyboard.press("Control+k")
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("combobox")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    states.append(
        page.evaluate("""() => {
        const element = document.activeElement;
        return [element.tagName, element.getAttribute('aria-label'), element.getAttribute('role')];
    }""")
    )
    page.set_viewport_size({"width": 390, "height": 844})
    expect(sidebar).to_be_hidden()
    header.locator("button:visible").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    states.append([element.bounding_box() for element in (main, header)])


@pytest.mark.parametrize(("language", "theme"), [("zh-CN", "light"), ("en-US", "dark")])
def test_original_shell_geometry_and_keyboard(language, theme, tmp_path):
    owner = json.loads(Path(os.environ["MEMSTACK_QA_LAYOUT_OWNER"]).read_bytes())
    bookmark = f"/tenant/{owner['tenant_id']}/plugins"
    geometry = []
    with workbench_language(owner, language), sync_playwright() as pw:
        browser = pw.chromium.launch()
        for host, origin in [
            ("original", os.environ["MEMSTACK_QA_COMPAT_ORIGIN"]),
            ("installed", os.environ["MEMSTACK_QA_VERTICAL_ORIGIN"]),
        ]:
            assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale=language, color_scheme=theme
            )
            page = ctx.new_page()
            page.set_default_timeout(30000)
            page.goto(origin + "/login")
            page.get_by_test_id("email-input").fill(owner["email"])
            page.get_by_test_id("password-input").fill(owner["password"])
            page.get_by_test_id("login-submit-button").click()
            expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)
            page.goto(origin + bookmark)
            main = page.locator("#main-content")
            header = main.locator("header").first
            sidebar = page.locator("aside").first
            expect(header).to_be_visible()
            expect(sidebar).to_be_visible()
            expect(page.locator("#pm-card-memstack-automation")).to_be_visible(timeout=60000)
            assert page.evaluate("document.documentElement.classList.contains('dark')") == (
                theme == "dark"
            )
            assert (
                page.evaluate("localStorage.getItem('i18nextLng')").split("-")[0]
                == language.split("-")[0]
            )
            states = []
            states.append([element.bounding_box() for element in (main, header, sidebar)])
            page.screenshot(path=tmp_path / f"{host}-{language}-{theme}.png", animations="disabled")
            exercise_shell_controls(page, states, sidebar, main, header)
            geometry.append(states)
            ctx.close()
        assert geometry[0] == geometry[1]
        browser.close()


@pytest.mark.parametrize(("language", "theme"), [("zh-CN", "light"), ("en-US", "dark")])
def test_original_advanced_search_field_geometry(language, theme, tmp_path):
    owner_path = os.environ.get("MEMSTACK_QA_LAYOUT_PROJECT_OWNER")
    if not owner_path:
        pytest.skip("requires an isolated project with Knowledge installed")
    owner = json.loads(Path(owner_path).read_bytes())
    bookmark = f"/tenant/{owner['tenant_id']}/project/{owner['project_id']}/advanced-search?workbench=full&q=layout"
    geometry = []
    with workbench_language(owner, language), sync_playwright() as pw:
        browser = pw.chromium.launch()
        for origin in (
            os.environ["MEMSTACK_QA_COMPAT_ORIGIN"],
            os.environ["MEMSTACK_QA_VERTICAL_ORIGIN"],
        ):
            assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale=language, color_scheme=theme
            )
            page = ctx.new_page()
            page.goto(origin + "/login")
            page.get_by_test_id("email-input").fill(owner["email"])
            page.get_by_test_id("password-input").fill(owner["password"])
            page.get_by_test_id("login-submit-button").click()
            expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)
            page.goto(origin + bookmark)
            # A signed fallback in the compatibility tab would compare the page to itself.
            source = (
                page
                if origin == os.environ["MEMSTACK_QA_COMPAT_ORIGIN"]
                else page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            )
            field = source.locator('input[type="search"][name="search"]').first
            expect(field).to_be_visible(timeout=60000)
            graph = (
                field.locator("xpath=ancestor::main[1]").locator("[class~='min-h-[420px]']").first
            )
            # The restored query runs immediately. Its longer busy label shrinks the input.
            retrieve = field.locator("xpath=ancestor::label[1]/following-sibling::button[1]")
            expect(retrieve).to_be_enabled(timeout=60000)
            field.evaluate("e => e.ownerDocument.fonts.ready")
            canvas = graph.locator("canvas").first
            expect(canvas).to_be_visible(timeout=30000)
            assert graph.evaluate("e => getComputedStyle(e).minHeight") == "420px"
            main = field.locator("xpath=ancestor::main[1]")
            surface = main.locator('[class~="dark:bg-surface-dark"]:visible').first
            expect(surface).to_be_visible()
            geometry.append(
                (
                    retrieve.inner_text(),
                    [item.bounding_box() for item in (field, graph, canvas)],
                    surface.evaluate("e => getComputedStyle(e).backgroundColor"),
                )
            )
            page.screenshot(
                path=tmp_path / f"search-{urlsplit(origin).port}-{language}-{theme}.png",
                animations="disabled",
            )
            ctx.close()
        assert geometry[0] == geometry[1]
