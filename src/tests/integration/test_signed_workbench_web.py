"""Exercise installed Agent and Knowledge pages using the full local Web host."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more, open_market

pytestmark = pytest.mark.integration


def _full_project():
    profile = "MEMSTACK_QA_MARKET_FULL"
    owner = os.getenv(profile + "_OWNER")
    origin = os.getenv(profile + "_ORIGIN")
    if not owner or not origin:
        pytest.skip("requires a disposable local full-workbench project")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    account = json.loads(Path(owner).read_bytes())
    return origin, account


@pytest.mark.parametrize(
    ("plugin", "title"), [("agent", "Agent chat"), ("knowledge", "Graph entities")]
)
def test_installed_workbench_page_and_rollback(plugin, title):
    origin, account = _full_project()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="en-US")
        catalog = open_market(page, "full", origin, account)
        assert urlsplit(catalog.json()["source"]).hostname in {"127.0.0.1", "localhost", "::1"}
        market = f"{origin.rstrip('/')}/tenant/{account['tenant_id']}/plugins?projectId={account['project_id']}"

        def details():
            page.goto(market)
            page.locator("#pm-card-memstack-" + plugin).click()
            page.locator(".pm-spec select option").first.wait_for(state="attached")

        details()
        active = page.locator(".pm-spec dd").first
        previous_version, version = ("1.2.0", "1.3.1") if plugin == "agent" else ("1.1.0", "1.2.0")
        if active.inner_text() != previous_version:
            apply(page, previous_version)
        apply(page, version)
        button = page.locator(".pm-page-list button").filter(has_text=re.compile(title, re.I))
        guest = page.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")

        def operation(name):
            return lambda response: (
                urlsplit(response.url).path.endswith("/commands")
                and response.request.method == "POST"
                and response.request.post_data_json.get("command_id") == name
            )

        if plugin == "agent":
            button.click()
            expect(guest.locator(".chat-history-viewport")).to_be_visible(timeout=20000)
            with page.expect_response(operation("chat-create")) as created:
                guest.locator("aside").get_by_role(
                    "button", name=re.compile("New conversation|新会话")
                ).click()
            assert created.value.ok, (created.value.status, created.value.json().get("detail"))
            expect(guest.locator("input")).to_have_value(re.compile("New conversation|新会话"))
        else:
            with (
                page.expect_response(operation("list-entities")) as entities,
                page.expect_response(operation("entity-types")) as types,
            ):
                button.click()
            assert entities.value.ok and types.value.ok
            search = guest.get_by_role("textbox")
            search.fill("package-test")
            expect(page).to_have_url(re.compile(r"[?&]q=package-test(&|$)"))
            expect(search).to_be_focused()
            page.reload()
            expect(search).to_have_value("package-test", timeout=20000)

        details()
        with page.expect_response(
            lambda response: urlsplit(response.url).path.endswith("/rollback"), timeout=60000
        ) as rollback:
            more(page, "Roll back to|回退至")
        assert rollback.value.ok
        expect(active).to_have_text(previous_version, timeout=60000)
        if plugin == "knowledge":
            expect(button).to_have_count(0)
        else:
            page.goto(
                f"{origin}/agent/chat?tenant={account['tenant_id']}&project={account['project_id']}&businessPackage=memstack-agent"
            )
            expect(
                guest.get_by_role("button", name=re.compile("New conversation|新会话"))
            ).to_be_visible(timeout=30000)
            expect(guest.locator(".agent-transcript")).to_be_visible()
            expect(guest.locator(".chat-history-viewport")).to_have_count(0)
        browser.close()
