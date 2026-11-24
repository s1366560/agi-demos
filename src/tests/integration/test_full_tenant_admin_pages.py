"""Read original tenant administration pages on the source-free full Web host."""

import json
import os
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_TENANT_ADMIN_OWNER"),
        reason="requires a local QA tenant owner and the full and compatibility Web hosts",
    ),
]


def sign_in(page, owner):
    page.get_by_test_id("email-input").fill(owner["email"])
    page.get_by_test_id("password-input").fill(owner["password"])
    page.get_by_test_id("login-submit-button").click()
    expect(page.get_by_test_id("login-submit-button")).to_have_count(0)


@pytest.fixture
def full_page():
    origin = os.getenv("MEMSTACK_QA_TENANT_ADMIN_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    owner = json.loads(Path(os.environ["MEMSTACK_QA_TENANT_ADMIN_OWNER"]).read_bytes())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.set_default_timeout(30000)
        page.goto(f"{origin}/login")
        sign_in(page, owner)
        yield page, origin, owner
        browser.close()


def test_tenant_administration_scoped_reads(full_page):
    page, origin, owner = full_page
    tenant = owner["tenant_id"]

    def assert_reads(open_page, suffixes):
        with ExitStack() as stack:
            reads = [
                stack.enter_context(
                    page.expect_response(
                        lambda r, suffix=suffix: (
                            r.request.method == "GET"
                            and urlsplit(r.url).path == f"/api/v1/tenants/{tenant}/{suffix}"
                        )
                    )
                )
                for suffix in suffixes
            ]
            open_page()
        assert all(response.value.ok for response in reads)

    for route, suffixes in (
        ("users", ["members", "invitations"]),
        ("audit-logs", ["audit-logs"]),
        ("org-settings/info", ["stats"]),
        ("org-settings/smtp", ["smtp-config"]),
        ("org-settings/registry", ["registries"]),
    ):
        assert_reads(lambda route=route: page.goto(f"{origin}/tenant/{tenant}/{route}"), suffixes)
    for tab, link, suffixes in (
        ("members", "users", ["members", "invitations"]),
        ("audit", "audit-logs", ["audit-logs"]),
    ):
        page.goto(f"{origin}/tenant/{tenant}/org-settings/{tab}")
        assert_reads(page.locator(f'a[href="/tenant/{tenant}/{link}"]').last.click, suffixes)


def test_compatibility_login_restores_scoped_path_query_and_fragment(full_page):
    page, origin, owner = full_page
    path = f"/tenant/{owner['tenant_id']}/org-settings/clusters?qa=readonly#node"
    page.goto(origin + path)
    link = page.locator('a[href*=":3001/"]')
    destination = link.get_attribute("href")
    assert destination == f"http://{urlsplit(origin).hostname}:3001{path}"
    link.click()
    expect(page.get_by_test_id("login-submit-button")).to_be_visible()
    sign_in(page, owner)
    expect(page).to_have_url(destination)
    expect(page.get_by_role("heading", name="Clusters", exact=True)).to_be_visible(timeout=30000)
    expect(page.get_by_role("button", name="Manage Clusters")).to_be_visible()
