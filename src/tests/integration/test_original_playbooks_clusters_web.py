"""Install the full-client Playbook and Cluster views from the loopback development registry."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, open_market

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_ORIGINAL_VIEWS_OWNER"),
        reason="requires a disposable local project owner and published 1.3.0 packages",
    ),
]


@pytest.fixture
def session():
    account = json.loads(Path(os.environ["MEMSTACK_QA_ORIGINAL_VIEWS_OWNER"]).read_bytes())
    origin = os.getenv("MEMSTACK_QA_ORIGINAL_VIEWS_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.set_default_timeout(25000)
        catalog = open_market(page, "full", origin, account)
        assert urlsplit(catalog.json()["source"]).hostname in {"127.0.0.1", "localhost", "::1"}
        yield page, origin, account
        browser.close()


def install(page, name):
    page.locator("#pm-card-memstack-" + name).click()
    expect(page.locator(".pm-spec")).to_be_visible(timeout=90000)
    version = "1.3.1" if name == "automation" else "1.3.0"
    if page.locator(".pm-spec dd").first.inner_text() != version:
        apply(page, version)


def command(name):
    return lambda r: (
        r.request.method == "POST"
        and urlsplit(r.url).path.endswith("/commands")
        and r.request.post_data_json["command_id"] == name
    )


def test_original_playbook_library_and_verdict_timeline(session):
    page, _, _ = session
    install(page, "automation")
    with page.expect_response(command("list-verdicts")) as verdicts:
        page.locator(".pm-page-list").get_by_role("button", name="Project playbooks").click()
    assert verdicts.value.ok, verdicts.value.status
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(
        frame.get_by_text(re.compile("Reflection verdicts|反思裁决"), exact=True)
    ).to_be_visible()
    with page.expect_response(command("list-playbooks")) as books:
        frame.get_by_role("button", name=re.compile("Refresh|刷新")).click()
    assert books.value.ok


def test_original_cluster_management_create_edit_delete(session):
    page, origin, account = session
    page.goto(f"{origin}/tenant/{account['tenant_id']}/plugins")
    install(page, "environments")
    with page.expect_response(command("environment-inventory")) as inventory:
        page.locator(".pm-page-list").get_by_role("button", name="Clusters", exact=True).click()
    assert inventory.value.ok, inventory.value.status
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    name = "Signed cluster " + uuid4().hex[:10]
    frame.get_by_role("button", name=re.compile("Add Cluster|添加集群|创建集群")).click()
    dialog = frame.get_by_role("dialog")
    dialog.locator("input#name").fill(name)
    with page.expect_response(command("write-cluster")) as created:
        dialog.locator(".ant-modal-footer .ant-btn-primary").click()
    assert created.value.ok, created.value.status
    row = frame.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible()
    row.get_by_role("button", name=re.compile("Edit|编辑")).click()
    name += " edited"
    dialog.locator("input#name").fill(name)
    with page.expect_response(command("write-cluster")) as updated:
        dialog.locator(".ant-modal-footer .ant-btn-primary").click()
    assert updated.value.ok, updated.value.status
    row = frame.get_by_role("row").filter(has_text=name)
    row.get_by_role("button", name=re.compile("Delete|删除")).click()
    with page.expect_response(command("delete-cluster")) as deleted:
        frame.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
    assert deleted.value.ok, deleted.value.status
    expect(row).to_have_count(0)


@pytest.mark.parametrize(
    ("plugin", "prior", "current", "title", "old_view", "new_view"),
    [
        (
            "automation",
            "1.2.2",
            "1.3.1",
            "Project playbooks",
            "section[aria-live]",
            "section.rounded-md",
        ),
        ("environments", "1.2.0", "1.3.0", "Clusters", "ul,ol,table,section", ".ant-table"),
    ],
)
def test_original_view_switches_with_installed_release(
    session, plugin, prior, current, title, old_view, new_view
):
    from src.tests.integration.marketplace_browser import more

    page, origin, account = session
    market_url = f"{origin}/tenant/{account['tenant_id']}/plugins"
    if plugin == "automation":
        market_url += "?projectId=" + account["project_id"]

    def detail():
        page.goto(market_url)
        page.locator("#pm-card-memstack-" + plugin).click()
        expect(page.locator(".pm-spec")).to_be_visible(timeout=90000)

    def verify(selector):
        page.locator(".pm-page-list").get_by_role("button", name=title, exact=True).click()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(frame.locator(selector).first).to_be_visible(timeout=45000)
        return frame

    detail()
    if page.locator(".pm-spec dd").first.inner_text() != prior:
        apply(page, prior)
    apply(page, current)
    verify(new_view)
    detail()
    more(page, "Roll back to|回退至")
    expect(page.locator(".pm-spec dd").first).to_have_text(prior, timeout=45000)
    old = verify(old_view)
    expect(old.locator(new_view)).to_have_count(0)
    detail()
    apply(page, current)
    verify(new_view)
