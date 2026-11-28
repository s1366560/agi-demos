"""Search from the shared Knowledge page with the installed, signed Sidecar target."""

import json
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from .marketplace_browser import business_release
from .test_fixed_workbench_market import _details, _native, _open
from .test_native_package_pages import BASE, PackageSession

pytestmark = pytest.mark.integration


def test_approved_search_and_revocation_on_native_page():
    owner_path = os.getenv("MEMSTACK_QA_DEVICE_SEARCH_OWNER")
    if not owner_path or not os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP"):
        pytest.skip("requires a disposable full Electron window and installed Knowledge package")
    owner = json.loads(Path(owner_path).read_bytes())
    scope = {key: owner[key] for key in ("tenant_id", "project_id")}
    with sync_playwright() as pw:
        page = _native(pw, owner, "project")
        version = business_release("knowledge")
        expect(_details(page, "knowledge")).to_have_text(version, timeout=90000)
        session = PackageSession(page, scope, "memstack-knowledge")
        release = session.cloud(
            BASE + "/npm/resolve", {"package_name": "@memstack/knowledge", "version": version}
        )
        assert release["digest"] == session.record()["actual_digest"]
        token, grant = session.approve(release["archive_base64"])
        try:
            guest = _open(page, "Knowledge")
            button = guest.get_by_role(
                "button", name=re.compile("Search on this device|在本机检索")
            )
            panel = button.locator("xpath=ancestor::form")
            query = uuid4().hex
            panel.locator("input").fill(query)
            panel.locator("textarea").fill("First line\n" + query + " local match")
            panel.get_by_role("button").click()
            expect(panel.locator("pre")).to_contain_text(query, timeout=60000)
            hit = json.loads(panel.locator("pre").inner_text())["hits"]
            assert hit == [{"id": "document", "line": 2, "excerpt": query + " local match"}]
        finally:
            session.device("revoke", token, **grant)
        panel.get_by_role("button").click()
        expect(panel.locator("pre")).to_contain_text(
            re.compile("grant|denied|unavailable"), timeout=60000
        )
