"""Run an externally published two-version plugin through either Web host on loopback.

Set MEMSTACK_QA_MARKET_PLUGIN to the fixture plugin ID from rich_page_publisher.
Each host takes MEMSTACK_QA_MARKET_{PACKAGE_HOST,FULL}_{ORIGIN,OWNER}. OWNER names the
disposable account JSON containing email, password, project_id, and (for full) tenant_id.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, is_catalog, more, open_market

pytestmark = pytest.mark.integration


def workspace_state(catalog):
    workspace = next(
        item for item in catalog.json()["items"] if item["plugin_id"] == "memstack-workspace"
    )
    installation = workspace["installation"] or {}
    return tuple(
        installation.get(field)
        for field in ("actual_digest", "actual_generation", "desired_revision")
    )


def cloud_label(
    page: Page, revision: int, expected_digest: str, plugin: str, snapshot: Path | None = None
):
    page.locator(".pm-detail-actions").get_by_role(
        "button", name=re.compile("^(Open feature|打开功能)$")
    ).click()
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(frame.get_by_role("heading", name=f"Inventory labels {revision}")).to_be_visible()
    with page.expect_response(
        lambda r: urlsplit(r.url).path.endswith(f"/{plugin}/commands")
    ) as call:
        frame.get_by_role("button", name="Cloud label").click()
    assert call.value.ok
    assert call.value.request.post_data_json["expected_digest"] == expected_digest
    expect(
        frame.get_by_role("button", name="Cloud label").locator(
            "xpath=following-sibling::output[1]"
        )
    ).to_contain_text(f"python-{revision}")
    if os.getenv("MEMSTACK_QA_MARKET_WORKER") == "1":
        worker = frame.get_by_role("button", name="Worker label")
        worker.click()
        expect(worker.locator("xpath=following-sibling::output[1]")).to_contain_text(
            f"worker-{revision}"
        )
    expect(frame.get_by_role("button", name="Device label")).to_have_count(0)
    if snapshot:
        page.screenshot(path=snapshot)
    back = page.get_by_role("link", name=re.compile("Back to marketplace|返回插件市场"))
    if back.count():
        back.click()
    else:
        page.go_back()
    expect(page.locator(".pm-spec")).to_be_visible(timeout=30000)


@pytest.mark.parametrize("host", ["package-host", "full"])
def test_unknown_npm_release_through_web(host, tmp_path):
    profile = "MEMSTACK_QA_MARKET_" + host.upper().replace("-", "_")
    if not all(
        os.getenv(k) for k in (profile + "_ORIGIN", profile + "_OWNER", "MEMSTACK_QA_MARKET_PLUGIN")
    ):
        pytest.skip("requires loopback host, disposable project owner, and the inventory fixture")
    origin = os.environ[profile + "_ORIGIN"].rstrip("/")
    assert urlsplit(origin).scheme in ("http", "https")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    account = json.loads(Path(os.environ[profile + "_OWNER"]).read_bytes())
    plugin = os.environ["MEMSTACK_QA_MARKET_PLUGIN"]
    assert re.fullmatch(r"memstack-inventory-market-qa(?:-[a-z0-9-]+)?", plugin)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 940})
        page.set_default_timeout(20000)
        runtime_errors = []
        page.on("pageerror", lambda error: runtime_errors.append(str(error)))
        catalog = open_market(page, host, origin, account)
        baseline = workspace_state(catalog)
        market = page.get_by_test_id("plugin-market")
        expect(market).to_be_visible()
        page.locator(f"[id='pm-card-{plugin}']").click()
        current = page.locator(".pm-spec dd").first
        if any(
            item["plugin_id"] == plugin and item["installation"] for item in catalog.json()["items"]
        ):
            more(page, "Uninstall|卸载")
        expect(current).to_have_text(re.compile("^(Inactive|未运行)$"), timeout=30000)
        digests = []
        for revision in (1, 2):
            with page.expect_response(
                lambda r: urlsplit(r.url).path.endswith("/npm/apply")
            ) as selected:
                apply(page, f"1.{revision}.0")
            response = selected.value
            assert response.ok and response.json()["plugin_id"] == plugin
            digest = response.json()["actual_digest"]
            assert response.request.post_data_json["expected_digest"] == digest
            digests.append(digest)
            cloud_label(page, revision, digest, plugin, tmp_path / f"{host}-{revision}.png")
        assert digests[0] != digests[1]
        more(page, "Roll back|回退至")
        expect(current).to_have_text("1.1.0")
        cloud_label(page, 1, digests[0], plugin)
        more(page, "Uninstall|卸载")
        expect(current).to_have_text(re.compile("^(Inactive|未运行)$"), timeout=30000)
        expect(page.locator(".pm-detail-actions .pm-primary")).to_have_text(
            re.compile("^(Install|安装)$")
        )
        with page.expect_response(is_catalog) as listed:
            page.get_by_role(
                "button", name=re.compile("^(Back to marketplace|返回插件市场)$")
            ).click()
            page.reload()
        assert workspace_state(listed.value) == baseline
        expect(page.locator("vite-error-overlay")).to_have_count(0)
        assert not runtime_errors
        browser.close()
