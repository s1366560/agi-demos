"""Compare the installed Chat page with the original workbench inside the same Web shell."""

import json
import os
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from .workbench_language import workbench_language

pytestmark = pytest.mark.integration


def sidebar_count(page):
    labels = (
        ("全部", "此计算机", "云端")
        if page.evaluate("navigator.language").startswith("zh")
        else ("All", "This computer", "Cloud")
    )
    sidebar = page.locator("aside").first
    for label in labels:
        expect(sidebar.get_by_role("button", name=label, exact=True)).to_be_visible()
    sidebar_count = sidebar.locator("p").filter(
        has_text=re.compile(r"^\s*\d+\s+(conversations?|个对话)\s*$")
    )
    expect(sidebar_count).to_be_visible()
    return sidebar_count.inner_text()


def scroll_welcome(page, greeting, draft):
    # At laptop height the welcome cards scroll independently of the pinned composer.
    page.set_viewport_size({"width": 1440, "height": 620})
    reader = greeting.locator("xpath=ancestor::*[contains(@class, 'overflow-y-auto')][1]")
    assert reader.evaluate("e => e.scrollHeight - e.clientHeight") > 48
    reader.hover()
    page.mouse.wheel(0, 120)
    expect(draft).to_be_in_viewport()
    expect(reader).not_to_have_js_property("scrollTop", 0)
    top = reader.evaluate("e => e.scrollTop")
    draft.focus()
    assert reader.evaluate("e => e.scrollTop") == top
    reader.evaluate("e => e.scrollTop = 0")
    page.set_viewport_size({"width": 1440, "height": 900})


def check_chat(page, document, screenshot, has_recent_skills):
    chat = document.get_by_role("main", name=re.compile("^(Chat|聊天)$"))
    draft = chat.get_by_test_id("chat-input")
    expect(draft).to_be_visible(timeout=30000)
    skip = document.get_by_role("button", name=re.compile("^(Skip tour|跳过引导)$"))
    if skip.is_visible():
        skip.click()
    inbox = chat.get_by_role(
        "button", name=re.compile("Open Activity and My Work|打开动态和我的工作")
    )
    activity_label = inbox.get_by_text(re.compile("Activity|动态"))
    expect(activity_label).to_be_visible()
    page.set_viewport_size({"width": 1180, "height": 900})
    expect(inbox).to_be_visible()
    expect(activity_label).to_be_hidden()
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(activity_label).to_be_visible()
    splitter = chat.get_by_role("separator")
    mode = chat.get_by_role("button", name=re.compile("^(Chat mode|聊天模式)$"))
    expect(mode).to_have_attribute("aria-pressed", "true")
    for name in ("Task mode|任务模式", "Code mode|代码模式", "Canvas mode|画布模式"):
        expect(chat.get_by_role("button", name=re.compile(f"^({name})$"))).to_be_visible()
    for name in ("Permission mode|授权模式", "Thinking level|思考级别"):
        expect(chat.get_by_title(re.compile(f"^({name})$"))).to_be_visible()
    expect(chat.get_by_title(re.compile("^Switch Model$|^切换模型$"))).to_be_visible()
    expect(chat.get_by_text(re.compile("^(Memories|记忆)$"))).to_be_visible()
    # This fixture has conversations and used skills. Both arrive after the initial empty page.
    # Wait for their visible content before comparing the centered welcome screen.
    expect(
        chat.get_by_role("button", name=re.compile("Continue where you left off|继续上次的对话"))
    ).to_be_visible(timeout=30000)
    recent = chat.get_by_text(re.compile("^(Recently Used|最近使用)$")).filter(visible=True)
    expect(recent).to_have_count(int(has_recent_skills), timeout=30000)
    greeting = chat.get_by_role("heading", level=2).first
    expect(greeting).to_be_visible()
    expect(chat.get_by_role("heading", level=3)).to_have_count(3)
    page.evaluate("document.fonts.ready")
    draft.evaluate("e => e.ownerDocument.fonts.ready")
    boxes = {
        label: target.bounding_box()
        for label, target in (
            ("chat", chat),
            ("draft", draft),
            ("welcome", greeting),
            ("splitter", splitter),
            ("activity", inbox),
            ("layout", mode),
        )
    }
    assert all(boxes.values())
    page.screenshot(path=screenshot, animations="disabled")
    scroll_welcome(page, greeting, draft)
    draft.fill("workbench layout check")
    draft.press("Shift+Enter")
    expect(draft).to_have_value("workbench layout check\n")
    draft.fill("")
    # Resizing the original composer moves its grab handle while the status bar stays anchored.
    handle = boxes["splitter"]
    x = handle["x"] + handle["width"] / 2
    y = handle["y"] + handle["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 40, steps=8)
    page.mouse.up()
    expect(splitter).to_be_visible()
    assert splitter.bounding_box()["y"] < handle["y"]
    assert mode.bounding_box()["y"] == pytest.approx(boxes["layout"]["y"], abs=1)
    typography = {
        name: element.evaluate("""e => {
            const style = getComputedStyle(e);
            return [style.fontSize, style.lineHeight, style.fontWeight, style.color];
        }""")
        for name, element in (("welcome", greeting), ("draft", draft), ("layout", mode))
    }
    return boxes, typography, sidebar_count(page)


@pytest.fixture
def owner():
    path = os.getenv("MEMSTACK_QA_AGENT_LAYOUT_OWNER")
    if not path:
        pytest.skip("requires a local original workbench and an installed Agent QA project")
    return json.loads(Path(path).read_bytes())


def is_project_context(response, project, installed, view):
    path = urlsplit(response.url).path
    if not installed:
        return response.ok and path.endswith(f"/projects/{project}/{view}")
    if not response.ok or not path.endswith("/memstack-agent/commands"):
        return False
    args = response.request.post_data_json or {}
    return (
        args.get("command_id") == "chat-project-context"
        and args.get("project_id") == project
        and args.get("payload", {}).get("view") == view
    )


@contextmanager
def workbench(browser, account, installed, language, theme, conversation=""):
    origin = os.environ["MEMSTACK_QA_VERTICAL_ORIGIN" if installed else "MEMSTACK_QA_COMPAT_ORIGIN"]
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, locale=language, color_scheme=theme
    )
    try:
        page = context.new_page()
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)
        params = {"projectId": account["project_id"]}
        if not installed:
            params["workbench"] = "full"
        path = f"/tenant/{account['tenant_id']}/agent-workspace"
        if conversation:
            path += "/" + conversation
        with ExitStack() as project_context:
            if not conversation:
                for view in ("stats", "trending", "recent-skills"):
                    project_context.enter_context(
                        page.expect_response(
                            lambda response, view=view: is_project_context(
                                response, account["project_id"], installed, view
                            ),
                            timeout=30000,
                        )
                    )
            page.goto(f"{origin}{path}?{urlencode(params)}")
        document = (
            page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            if installed
            else page
        )
        yield page, document
    finally:
        context.close()


@pytest.mark.parametrize(("language", "theme"), [("en-US", "light"), ("zh-CN", "dark")])
def test_installed_agent_chat_matches_original_workbench(
    owner, conversation, language, theme, tmp_path
):
    screens = []
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        ).raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        recent = client.get(f"/projects/{owner['project_id']}/recent-skills").raise_for_status()
    with workbench_language(owner, language), sync_playwright() as pw:
        browser = pw.chromium.launch()
        for installed in (False, True):
            with workbench(browser, owner, installed, language, theme) as (page, document):
                source = "installed" if installed else "original"
                screens.append(
                    check_chat(
                        page,
                        document,
                        tmp_path / f"{source}-{language}-{theme}.png",
                        bool(recent.json()["skills"]),
                    )
                )
        browser.close()
    (
        (original_geometry, original_type, original_count),
        (installed_geometry, installed_type, installed_count),
    ) = screens
    for control, original_box in original_geometry.items():
        assert installed_geometry[control] == pytest.approx(original_box, abs=1), control
    assert installed_type == original_type
    assert installed_count == original_count


@pytest.fixture
def conversation(owner):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        created = client.post(
            "/agent/conversations",
            json={"project_id": owner["project_id"], "title": "Composer menu integration"},
        )
        created.raise_for_status()
        conversation_id = created.json()["id"]
        try:
            yield conversation_id
        finally:
            deleted = client.delete(
                "/agent/conversations/" + conversation_id,
                params={"project_id": owner["project_id"]},
            )
            deleted.raise_for_status()


def conversation_controls(document):
    chat = document.get_by_role("main", name="Chat", exact=True)
    draft = chat.get_by_test_id("chat-input")
    # Both routers can show the unselected composer while the bookmarked conversation is loading.
    expect(chat.get_by_title("Composer menu integration", exact=True)).to_be_visible(timeout=30000)
    expect(draft).to_be_enabled(timeout=30000)
    chat.get_by_title("Add", exact=True).click()
    menu = chat.get_by_role("menu")
    menu.get_by_role("textbox").fill("template")
    menu.get_by_role("menuitem", name=re.compile("template", re.I)).click()
    templates = chat.get_by_role("textbox", name=re.compile("Search templates", re.I))
    templates.fill("missing-integration-template")
    expect(chat.get_by_text("No templates found", exact=True)).to_be_visible()
    templates.fill("Write Tests")
    chat.get_by_role("button", name=re.compile("^Write Tests")).click()
    prompt = draft.input_value()
    assert "test" in prompt.lower()
    draft.fill("")
    draft.press("Control+f")
    search = chat.get_by_role("textbox", name=re.compile("Search in conversation", re.I))
    expect(search).to_be_focused()
    search.fill("missing-integration-message")
    expect(search).to_have_value("missing-integration-message")
    expect(search.locator("..").get_by_text("0 results", exact=True)).to_be_visible()
    search.press("Escape")
    expect(search).to_have_count(0)
    choices = {"template_prompt": prompt}
    for title in ("Permission mode", "Thinking level", "Switch Model"):
        switch = chat.get_by_title(title, exact=True)
        expect(switch).to_be_enabled(timeout=30000)
        switch.click()
        options = chat.get_by_role("listbox").get_by_role("option")
        expect(options.first).to_be_visible(timeout=30000)
        choices[title] = options.all_text_contents()
        expect(chat.get_by_role("option", selected=True)).to_have_count(1)
        switch.press("Escape")
        expect(options).to_have_count(0)
    return choices


def test_installed_conversation_composer_menus_and_reload(owner, conversation):
    states = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for installed in (False, True):
            with workbench(browser, owner, installed, "en-US", "light", conversation) as (
                page,
                document,
            ):
                before = conversation_controls(document)
                page.reload()
                assert conversation_controls(document) == before
                states.append(before)
        browser.close()
    # The legacy catalog includes unconfigured providers. Signed pages advertise only the
    # tenant's routable models. Both present the original Default and Auto controls.
    for state in states:
        models = state.pop("Switch Model")
        assert models[0].startswith("Default")
        assert models[1].startswith("Auto (Router)")
    assert states[1] == states[0]


def test_installed_composer_saves_conversation_preferences(owner, conversation):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        tenant_provider = client.get(f"/llm-providers/tenants/{owner['tenant_id']}/provider")
        tenant_provider.raise_for_status()
        configured_model = tenant_provider.json()["llm_model"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            with workbench(browser, owner, True, "en-US", "light", conversation) as (
                page,
                document,
            ):
                chat = document.get_by_role("main", name="Chat", exact=True)
                for title, value in (
                    ("Thinking level", re.compile("^Thinking: low")),
                    ("Switch Model", configured_model),
                ):
                    control = chat.get_by_title(title, exact=True)
                    expect(control).to_be_enabled(timeout=30000)
                    control.click()
                    with page.expect_response(
                        lambda response: response.ok
                        and urlsplit(response.url).path.endswith("/memstack-agent/commands")
                        and (response.request.post_data_json or {}).get("command_id")
                        == "chat-composer-save"
                        and response.request.post_data_json["payload"]["conversation_id"]
                        == conversation,
                        timeout=60000,
                    ):
                        chat.get_by_role("option", name=value, exact=True).click()
                    expect(control).to_contain_text(value, timeout=30000)
                page.reload()
                expect(chat.get_by_title("Thinking level", exact=True)).to_contain_text(
                    "Thinking: low", timeout=30000
                )
                expect(chat.get_by_title("Switch Model", exact=True)).to_contain_text(
                    configured_model, timeout=30000
                )
                config = client.get(
                    "/agent/conversations/" + conversation,
                    params={"project_id": owner["project_id"]},
                )
                config.raise_for_status()
                persisted = config.json()["agent_config"]
                assert persisted["llm_overrides"]["reasoning_effort"] == "low"
                assert persisted["llm_model_override"] == configured_model
            browser.close()


def test_installed_status_bar_follows_project_runtime(owner):
    # Read the live project status and inspect only the actions allowed for this account.
    english = json.loads(
        (
            Path(__file__).resolve().parents[3] / "plugins/business/agent/ui/web/locales/en-US.json"
        ).read_bytes()
    )["agent"]["lifecycle"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        with workbench(browser, owner, True, "en-US", "light") as (page, document):
            with page.expect_response(
                lambda response: is_project_context(
                    response, owner["project_id"], True, "lifecycle"
                ),
                timeout=30000,
            ) as observed:
                page.reload()
            status = observed.value.json()
            chat = document.get_by_role("main", name="Chat", exact=True)
            expect(
                chat.get_by_text(english["states"][status["lifecycle_state"]], exact=True)
            ).to_be_visible(timeout=30000)
            labels = {
                "stop": "terminateInstance" if status["pool_managed"] else "stopAgent",
                "restart": "restartAgent",
                "pause": "pause",
                "resume": "resume",
            }
            for action, label in labels.items():
                button = chat.get_by_role("button", name=english["controls"][label], exact=True)
                if action not in status["allowed_actions"]:
                    expect(button).to_have_count(0)
                    continue
                expect(button).to_be_visible()
                if action in ("stop", "restart"):
                    button.click()
                    cancel = document.get_by_role(
                        "button", name=english["controls"]["cancel"], exact=True
                    )
                    cancel.click()
                    expect(cancel).to_be_hidden()
        browser.close()
