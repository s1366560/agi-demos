"""Exercise original installed business controls on disposable full clients."""

import json
import os
import re
from contextlib import ExitStack, nullcontext
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import (
    apply,
    business_release,
    install_previous,
    more,
)
from src.tests.integration.test_signed_directory_memory_views import (
    _guest,
    _native_market,
    _open_web,
    _page_button,
)

pytestmark = pytest.mark.integration
RELEASES = {name: business_release(name) for name in ("workspace", "knowledge")}


def _client(playwright, client):
    if client == "web":
        return _open_web(playwright)[0]
    endpoint = os.getenv("MEMSTACK_QA_ORIGINAL_PAGES_CDP")
    if not endpoint:
        pytest.skip("requires an isolated native Electron project marketplace")
    assert urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    page = playwright.chromium.connect_over_cdp(endpoint).contexts[0].pages[0]
    page.set_default_timeout(60000)
    owner = json.loads(Path(os.environ["MEMSTACK_QA_MARKET_FULL_OWNER"]).read_bytes())
    page.evaluate(
        "(tenant) => {location.hash = '/tenant/' + tenant + '/plugins?marketScope=project'}",
        owner["tenant_id"],
    )
    _native_market(page)
    return page


@pytest.mark.parametrize("client", ["web", "desktop"])
@pytest.mark.parametrize(
    ("package", "previous", "entry"),
    [
        ("knowledge", "1.4.0", "Memory editor"),
        ("workspace", "1.4.1", "Workspace directory"),
    ],
)
def test_restore_original_release(client, package, previous, entry):
    with sync_playwright() as pw:
        page = _client(pw, client)
        card = page.locator(f"#pm-card-memstack-{package}")
        card.click()
        install_previous(page, previous)
        button = page.locator(".pm-page-list").get_by_role("button", name=entry, exact=True)
        detail_hash = urlsplit(page.url).fragment
        apply(page, RELEASES[package])
        more(page, rf"Roll back to {re.escape(previous)}|回退至 {re.escape(previous)}")
        expect(page.locator(".pm-spec dd").first).to_have_text(previous, timeout=60000)
        button.click()
        guest = _guest(page)
        if package == "knowledge":
            expect(guest.get_by_label(re.compile("^(Title|标题)$"))).to_be_visible(timeout=60000)
            expect(guest.locator("#memory-title, .cloud-memory-editor input")).to_have_count(0)
        else:
            _open_first_workspace(guest, client)
            expect(guest.locator("h1,h2").first).to_be_visible(timeout=60000)
            expect(guest.get_by_role("tab", name=re.compile("Discussion|讨论"))).to_have_count(0)
        if client == "web":
            page.get_by_role("link", name="Back to plugin marketplace").click()
        else:
            page.evaluate("(hash) => {location.hash = hash}", detail_hash)
        detail = page.locator(".pm-spec")
        detail.or_(card).first.wait_for(timeout=60000)
        if not detail.is_visible():
            card.click()
        expect(detail).to_be_visible(timeout=60000)
        apply(page, RELEASES[package])
        button.click()
        if package == "knowledge":
            expect(guest.locator("#memory-title")).to_be_visible(timeout=60000)
        else:
            _open_first_workspace(guest, "web")
            expect(guest.get_by_role("tab", name=re.compile("Discussion|讨论"))).to_be_visible(
                timeout=60000
            )
            if client == "desktop":
                page.bring_to_front()
                create = page.locator(".desktop-workspace-heading-actions").get_by_role(
                    "button",
                    name=re.compile("New workspace|Create workspace|新建工作空间|创建工作区", re.I),
                )
                create.click()
                expect(page).to_have_url(re.compile(r"(?:/|%2F)workspaces(?:/|%2F)new(?:[?#&]|$)", re.I), timeout=30000)
                creation = page.frame_locator(
                    'iframe[title="Create workspace"][data-page-ready=true]'
                ).frame_locator("iframe")
                expect(creation.get_by_role("heading", level=1)).to_be_visible(timeout=90000)


def _open_first_workspace(guest, client):
    if client == "web":
        guest.locator("li a[aria-label]").first.click()
    else:
        guest.locator(".tenant-workspaces-grid article").first.get_by_role("button").click()


def test_write_objective_in_original_blackboard():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        guest.get_by_role("button", name="Add Objective", exact=True).click()
        dialog = guest.get_by_role("dialog")
        title = "QA signed workspace objective " + uuid4().hex[:8]
        dialog.get_by_role("textbox").first.fill(title)
        dialog.get_by_role("button", name="Create", exact=True).click()
        expect(guest.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)
        page.reload()
        expect(guest.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)


def test_native_memory_create_reindex_and_delete():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Memory editor").click()
        guest = _guest(page)
        title = "QA signed desktop memory " + uuid4().hex[:8]
        guest.locator("#memory-title").fill(title)
        guest.locator("textarea").fill("Created from the shared form in Electron.")
        guest.get_by_role("button", name=re.compile(r"^(Save Memory|保存记忆)$")).click()
        expect(page).to_have_url(re.compile(r"(?:/|%2F)memories(?:[?#&].*)?$", re.I), timeout=120000)
        guest.get_by_text(title, exact=True).first.click()
        expect(guest.get_by_role("heading", name=title)).to_be_visible(timeout=60000)
        retry = guest.get_by_role("button", name=re.compile("Reprocess|Reindex|重新处理|重新索引", re.I))
        expect(retry).to_be_enabled(timeout=120000)
        retry.click()
        expect(guest.get_by_text(re.compile(r"^(Completed|已完成)$")).first).to_be_visible(timeout=120000)
        page.reload()
        guest.get_by_role("button", name=re.compile(r"^(Delete|删除|删\s+除)$")).click()
        guest.get_by_role("dialog").get_by_role("button", name=re.compile(r"^(Delete|删除|删\s+除)$")).click()
        expect(page).to_have_url(re.compile(r"(?:/|%2F)memories(?:[?#&].*)?$", re.I), timeout=60000)
        expect(guest.get_by_text(title, exact=True)).to_have_count(0)


def test_web_editor_reindex_and_delete_memory():
    with sync_playwright() as pw:
        page, base = _open_web(pw)
        _page_button(page, "knowledge", RELEASES["knowledge"], "Memory editor").click()
        guest = _guest(page)
        title = "QA signed web memory " + uuid4().hex[:8]
        guest.locator("#memory-title").fill(title)
        guest.locator("textarea").fill("A record created from the installed original form.")

        def accepted(command):
            return (
                lambda r: r.url.endswith("/commands")
                and r.request.post_data_json.get("command_id") == command
            )

        with page.expect_response(accepted("save-memory"), timeout=60000) as saved:
            guest.get_by_role("button", name=re.compile(r"^(Save Memory|保存记忆)$")).click()
        assert saved.value.ok
        memory = saved.value.json()
        page.goto(base + "/memory/" + memory["id"])
        retry = guest.get_by_role("button", name=re.compile("Reprocess|Reindex|重新处理|重新索引", re.I))
        expect(retry).to_be_visible(timeout=60000)
        for _ in range(40):
            if retry.is_enabled():
                break
            page.wait_for_timeout(3000)
            page.reload()
            expect(retry).to_be_visible(timeout=60000)
        with page.expect_response(accepted("reindex-memory"), timeout=60000) as indexing:
            retry.click()
        assert indexing.value.ok, indexing.value.status
        completed = guest.get_by_text(re.compile(r"^(Completed|已完成)$")).first
        expect(completed).to_be_visible(timeout=120000)
        # A reload reads the persisted memory and its revision through the installed package.
        page.reload()
        expect(completed).to_be_visible(timeout=60000)
        guest.get_by_role("button", name=re.compile(r"^(Delete|删除|删\s+除)$")).click()
        with page.expect_response(accepted("delete-memory"), timeout=60000) as removed:
            guest.get_by_role("dialog").get_by_role("button", name=re.compile(r"^(Delete|删除|删\s+除)$")).click()
        assert removed.value.ok, removed.value.status


def test_native_blackboard_post_is_retained():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        tab = guest.get_by_role("tab", name=re.compile("Discussion|讨论"))
        tab.click()
        panel = guest
        title = "QA signed native discussion " + uuid4().hex[:8]
        create = panel.get_by_role("button", name=re.compile(r"^\+.*(Thread|Post|讨论|发帖|帖子)", re.I))
        back = panel.get_by_role("button", name=re.compile("Back|返回"))
        expect(create.or_(back).first).to_be_visible(timeout=60000)
        if back.is_visible():
            back.click()
        create.click()
        panel.locator("#blackboard-post-title").fill(title)
        panel.locator("#blackboard-post-content").fill("Posted from the shared workspace page.")
        panel.locator("#blackboard-post-content").locator("xpath=ancestor::div[.//button][1]").get_by_role("button").click()
        expect(panel.get_by_text(title, exact=True).first).to_be_visible(timeout=120000)
        page.reload()
        tab.click()
        expect(panel.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)


def test_web_blackboard_upload_and_preview_chunks():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        guest.get_by_role("tab", name=re.compile("Files")).click()
        region = guest.get_by_role("region", name="Shared files")
        name = "QA-board-" + uuid4().hex[:8] + ".txt"
        data = "Signed file begin\n" + "workspace content\n" * 3300 + "Signed file end"
        region.locator("input[type=file]").set_input_files(
            {"name": name, "mimeType": "text/plain", "buffer": data.encode()}
        )
        region.get_by_role("button", name=name, exact=True).click(timeout=90000)
        expect(guest.get_by_role("dialog").locator("pre")).to_have_text(data, timeout=90000)


def test_web_opens_installed_agent_from_original_board():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        page.locator("#pm-card-memstack-agent").click()
        versions = page.locator(".pm-spec select")
        release = versions.input_value()
        active = page.locator(".pm-spec dd").first
        if active.inner_text() != release:
            apply(page, release)
        page.locator(".pm-back").click()
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        open_chat = guest.get_by_role("link", name="Open in Agent Workspace")
        expect(open_chat).to_be_visible(timeout=60000)
        board_url = page.url
        open_chat.click()
        chat = page.locator('iframe[title="Agent chat"][data-page-ready=true]')
        expect(chat).to_be_visible(timeout=60000)
        chat_url = page.url
        assert chat_url != board_url
        page.go_back()
        expect(page).to_have_url(board_url)
        expect(open_chat).to_be_visible(timeout=60000)
        page.go_forward()
        expect(page).to_have_url(chat_url)
        expect(chat).to_be_visible(timeout=60000)
        page.reload()
        expect(page).to_have_url(chat_url)
        expect(chat).to_be_visible(timeout=60000)


def test_web_graph_loads_through_installed_original_controls():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Knowledge graph").click()
        view = _guest(page).get_by_test_id("memory-graph-page")
        expect(view).to_be_visible(timeout=60000)
        with page.expect_response(
            lambda response: response.url.endswith("/commands")
            and response.request.method == "POST"
            and response.request.post_data_json.get("command_id") == "read-graph",
            timeout=60000,
        ) as pending:
            view.get_by_role("button", name=re.compile(r"Reload Data|重新加载数据")).click()
        response = pending.value
        assert response.ok, response.status
        elements = response.json()["elements"]
        assert isinstance(elements["nodes"], list) and isinstance(elements["edges"], list)
        nodes = view.get_by_role("table", name=re.compile(r"Graph nodes|节点"))
        expect(nodes.locator("tbody tr")).to_have_count(len(elements["nodes"]))


def test_native_graph_refreshes_installed_original_projection():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Knowledge graph").click()
        view = _guest(page).get_by_test_id("memory-graph-page")
        expect(view).to_be_visible(timeout=60000)
        view.get_by_role("button", name=re.compile(r"Reload Data|重新加载数据")).click()
        nodes = view.get_by_role("table", name=re.compile(r"Graph nodes|节点"))
        expect(nodes.locator("tbody tr").first).to_be_visible(timeout=60000)


@pytest.mark.parametrize("client", ["web", "desktop"])
def test_installed_advanced_search_bookmark(client):
    with sync_playwright() as pw:
        page = _client(pw, client)
        _page_button(page, "knowledge", RELEASES["knowledge"], "Advanced search").click()
        guest = _guest(page)
        field = guest.locator('input[type="search"][name="search"]')
        expect(field).to_be_visible(timeout=60000)
        graph = guest.locator("[class~='min-h-[420px]']").first
        expect(graph.locator("canvas").first).to_be_visible(timeout=60000)
        assert graph.evaluate("e => getComputedStyle(e).minHeight") == "420px"
        loading = graph.get_by_text(re.compile("Loading graph|正在加载图谱", re.I))
        expect(loading).to_have_count(0, timeout=90000)
        viewport = graph.locator(".__________cytoscape_container").first
        node_count = viewport.evaluate("e => e._cyreg.cy.nodes().length")
        assert node_count > 0, "The search acceptance project must render its populated graph"
        field.fill("signed-knowledge-search")
        network = (
            page.expect_response(
                lambda response: response.url.endswith("/commands")
                and response.request.method == "POST"
                and response.request.post_data_json.get("command_id") == "search-project",
                timeout=60000,
            )
            if client == "web"
            else nullcontext()
        )
        with network as result:
            field.press("Enter")
        if result is not None:
            assert result.value.ok, result.value.status
            assert isinstance(result.value.json()["results"], list)
        expect(page).to_have_url(re.compile("signed-knowledge-search"), timeout=30000)
        page.reload()
        expect(field).to_have_value("signed-knowledge-search", timeout=60000)


def test_open_knowledge_session_survives_workspace_release_switches():
    from scripts.dev.verify_six_workbenches import installation_lock

    account = os.environ.get("MEMSTACK_QA_MARKET_FULL_OWNER")
    if not account:
        pytest.skip("requires an isolated project with both packages")
    owner = json.loads(Path(account).read_bytes())
    with ExitStack() as stack, sync_playwright() as pw:
        for package in ("knowledge", "workspace"):
            stack.enter_context(installation_lock(owner["tenant_id"], owner["project_id"], package))
        market = _client(pw, "web")
        knowledge = market.context.new_page()
        knowledge.goto(market.url)
        _page_button(knowledge, "knowledge", RELEASES["knowledge"], "Advanced search").click()
        frame = knowledge.locator("iframe[data-page-ready=true]").first
        expect(frame).to_be_visible(timeout=60000)
        digest = frame.get_attribute("data-release-digest")
        assert digest
        search = _guest(knowledge).locator('input[type="search"][name="search"]')
        market.locator("#pm-card-memstack-workspace").click()
        install_previous(market, "1.4.1")
        try:
            apply(market, RELEASES["workspace"])
            for tag in ("upgrade", "rollback"):
                if tag == "rollback":
                    more(market, r"Roll back to 1\.4\.1|回退至 1\.4\.1")
                    expect(market.locator(".pm-spec dd").first).to_have_text("1.4.1", timeout=60000)
                search.fill(tag + "-neighbor-search")
                with knowledge.expect_response(
                    lambda res: res.url.endswith("/commands")
                    and res.request.method == "POST"
                    and res.request.post_data_json.get("command_id") == "search-project",
                    timeout=60000,
                ) as operation:
                    search.press("Enter")
                assert operation.value.ok
                assert isinstance(operation.value.json()["results"], list)
                expect(frame).to_have_attribute("data-release-digest", digest)
        finally:
            if market.locator(".pm-spec dd").first.inner_text() != RELEASES["workspace"]:
                apply(market, RELEASES["workspace"])
            knowledge.close()


@pytest.mark.parametrize("client", ["web", "desktop"])
def test_original_task_details_bookmark(client):
    from src.tests.integration.test_signed_sidebar import qa_workspace

    with sync_playwright() as pw:
        page = _client(pw, client)
        owner = json.loads(Path(os.environ["MEMSTACK_QA_MARKET_FULL_OWNER"]).read_bytes())
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory")
        with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=60) as api:
            login = api.post(
                "/auth/token", data={"username": owner["email"], "password": owner["password"]}
            )
            login.raise_for_status()
            api.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            workspace = qa_workspace(api, owner, name="Workspace task bookmark QA")
            title = "Signed task detail " + uuid4().hex[:8]
            response = api.post(f"/workspaces/{workspace}/tasks", json={"title": title})
            response.raise_for_status()
            task = response.json()["id"]
        path = f"/tenant/{owner['tenant_id']}/project/{owner['project_id']}/workspaces/{workspace}/tasks/{task}"
        if client == "web":
            page.goto(os.environ["MEMSTACK_QA_MARKET_FULL_ORIGIN"] + path)
        else:
            page.evaluate("(path) => {location.hash = path}", path)
        title_heading = _guest(page).locator("aside").get_by_role("heading", name=title, exact=True)
        expect(title_heading).to_be_visible(timeout=90000)
        page.reload()
        expect(title_heading).to_be_visible(timeout=90000)


@pytest.mark.parametrize("client", ["web", "desktop"])
def test_original_project_overview_bookmark(client):
    owner = json.loads(Path(os.environ["MEMSTACK_QA_MARKET_FULL_OWNER"]).read_bytes())
    project, tenant = owner["project_id"], owner["tenant_id"]
    route = f"/tenant/{tenant}/project/{project}"
    title = "Project overview QA " + uuid4().hex[:10]
    with (
        sync_playwright() as pw,
        httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=60) as api,
    ):
        login = api.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        api.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        project_info = api.get("/projects/" + project, params={"tenant_id": tenant})
        project_info.raise_for_status()
        name = project_info.json()["name"]
        page = _client(pw, client)
        _page_button(page, "workspace", RELEASES["workspace"], "Project overview")
        response = api.post(
            "/memories/",
            json={
                "project_id": project,
                "title": title,
                "content": "Project overview recent memory",
            },
        )
        response.raise_for_status()
        identifier = response.json()["id"]
        try:
            if client == "web":
                page.goto(os.environ["MEMSTACK_QA_MARKET_FULL_ORIGIN"] + route)
            else:
                page.evaluate("(path) => {location.hash = path}", route)
            frame = page.frame_locator(
                'iframe[title="Project overview"][data-page-ready=true]'
            ).frame_locator("iframe")
            for restore in (False, True):
                if restore:
                    page.reload()
                expect(frame.get_by_text(name, exact=False).first).to_be_visible(timeout=90000)
                expect(frame.get_by_text(title, exact=True).first).to_be_visible(timeout=90000)
            if client == "web":
                frame.get_by_role("link", name=title).click()
                expect(page).to_have_url(re.compile(re.escape(route + "/memory/" + identifier)))
        finally:
            deleted = api.delete("/memories/" + identifier)
            assert deleted.is_success, deleted.status_code
