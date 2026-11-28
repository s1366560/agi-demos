"""Open Billing through the full Web tenant market, including a direct reload with no project."""

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_TENANT_MARKET_OWNER"),
        reason="requires a loopback full Web host, a QA tenant owner and published Billing",
    ),
]


def test_tenant_billing_page_without_a_selected_project():
    account = json.loads(Path(os.environ["MEMSTACK_QA_TENANT_MARKET_OWNER"]).read_bytes())
    origin = os.environ.get("MEMSTACK_QA_STANDARD_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0)
        url = origin + "/tenant/" + account["tenant_id"] + "/plugins?marketPlugin=memstack-billing"
        base = "/api/v1/tenant-packages/"
        with page.expect_response(lambda r: urlsplit(r.url).path == base + "npm/detail") as loaded:
            page.goto(url)
        response = loaded.value
        assert response.ok
        assert "project_id" not in parse_qs(urlsplit(response.url).query)
        market = page.get_by_test_id("plugin-market")
        if not (response.json()["installation"] or {}).get("running_version"):
            market.get_by_role("button", name=re.compile(r"^(Install|安装)$")).click()
            dialog = page.get_by_role("dialog")
            with page.expect_response(lambda r: urlsplit(r.url).path == base + "npm/apply") as done:
                dialog.get_by_role("button", name=re.compile("Approve and enable|批准并启用")).click()
            assert done.value.ok
            assert "project_id" not in done.value.request.post_data_json
        market.get_by_role("button", name=re.compile("Open feature|打开功能")).click()
        guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(guest.get_by_role("heading").first).to_be_visible()
        query = parse_qs(urlsplit(page.url).query)
        assert query["packageScope"] == ["tenant"] and "project" not in query
        page.reload()
        expect(guest.get_by_role("heading").first).to_be_visible()
        browser.close()
