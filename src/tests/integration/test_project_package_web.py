"""Build the package-only Web client and install/execute an official release in Chromium."""

import asyncio
import json
import os
import secrets
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright, expect
from sqlalchemy.ext.asyncio import async_sessionmaker

from plugins.business.billing.build import ROOT as BILLING, build_release
from src.host.transport import package_kernel
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_password_hash
from src.infrastructure.adapters.primary.web.routers import auth
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("WEB_PACKAGE_CHROMIUM_TESTS") != "1",
        reason="requires pnpm and Playwright Chromium",
    ),
]

ROOT = Path(__file__).resolve().parents[3]


async def test_build_login_install_and_execute_signed_page(tmp_path, db_session, monkeypatch):  # noqa: PLR0915
    output = tmp_path / "web"
    build = await asyncio.create_subprocess_exec(
        "pnpm",
        "exec",
        "vite",
        "build",
        "--mode",
        "project-packages",
        "--outDir",
        str(output),
        cwd=ROOT / "web",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    log, _ = await build.communicate()
    assert build.returncode == 0, log.decode()[-3000:]
    assert (output / "project-packages.html").exists() and not (output / "index.html").exists()
    password = secrets.token_urlsafe(28)
    for role in ("owner", "viewer"):
        db_session.add(
            User(
                id=role,
                email=f"{role}@example.test",
                hashed_password=get_password_hash(password),
                is_active=True,
                must_change_password=role == "viewer",
            )
        )
    await db_session.flush()
    db_session.add(Tenant(id="company", name="Company", slug="company", owner_id="owner"))
    await db_session.flush()
    for project in ("shared", "private"):
        db_session.add(Project(id=project, tenant_id="company", name=project, owner_id="owner"))
    await db_session.flush()
    for role in ("owner", "viewer"):
        db_session.add(
            UserTenant(id=f"membership-{role}", user_id=role, tenant_id="company", role="member")
        )
        db_session.add(
            UserProject(id=f"project-{role}", user_id=role, project_id="shared", role=role)
        )
    db_session.add(
        UserProject(id="private-owner", user_id="owner", project_id="private", role="owner")
    )
    await db_session.commit()
    settings = SimpleNamespace(
        secret_key=secrets.token_urlsafe(40),
        api_allowed_origins=[],
        package_application_runtime_url=None,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(package_kernel, "get_settings", lambda: settings)
    signer = Ed25519PrivateKey.generate()
    raw = build_release(
        json.loads((BILLING / "plans.json").read_bytes()), version="3.1.0", signer=signer
    )
    archive = tmp_path / "billing.mspkg"
    archive.write_bytes(raw)
    public = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    app = package_kernel.create_app()
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.mount("/", StaticFiles(directory=output), name="standalone-portal")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.02)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                context = await browser.new_context(locale="en-US")
                page = await context.new_page()

                async def login(role):
                    await page.get_by_label("Email", exact=True).fill(f"{role}@example.test")
                    await page.get_by_label("Password", exact=True).fill(password)
                    await page.get_by_role("button", name="Sign In", exact=True).click()

                await page.goto(origin + "/project-packages.html?tenant=company&project=shared")
                await login("owner")
                panel = page.get_by_test_id("plugin-market")
                await expect(panel.get_by_text("More actions", exact=True)).to_be_visible()
                await panel.get_by_label("Choose signed package").set_input_files(archive)
                await (
                    page.get_by_role("dialog")
                    .get_by_role("button", name="Approve and enable")
                    .click()
                )
                await expect(panel.get_by_label("Select version")).to_have_value("3.1.0")
                await (
                    page.frame_locator('[data-testid="signed-business-slot"]')
                    .get_by_role("button", name="Pro storage allowance")
                    .click()
                )
                await expect(panel.locator("pre")).to_contain_text("107374182400")
                await page.reload()
                await expect(page.get_by_test_id("signed-business-slot")).to_be_visible()
                second_tab = await context.new_page()
                await second_tab.goto(page.url)
                await expect(second_tab.get_by_test_id("signed-business-slot")).to_be_visible()
                await page.get_by_role("button", name="Logout", exact=True).click()
                await expect(page.get_by_test_id("signed-business-slot")).to_have_count(0)
                await expect(second_tab.get_by_label("Email", exact=True)).to_be_visible()
                await login("viewer")
                await expect(page.get_by_label("Current Password", exact=True)).to_be_visible()
                await page.reload()
                await expect(panel).to_have_count(0)
                await page.get_by_label("Current Password", exact=True).fill(password)
                await page.get_by_label("New Password", exact=True).fill(secrets.token_urlsafe(30))
                await page.get_by_role("button", name="Save", exact=True).click()
                await expect(panel).to_be_visible()
                await expect(panel.get_by_text("More actions", exact=True)).to_have_count(0)
                await page.goto(origin + "/project-packages.html?tenant=company&project=private")
                await expect(page.get_by_role("alert")).to_contain_text("do not have access")
                await expect(panel).to_have_count(0)
                await browser.close()
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)
