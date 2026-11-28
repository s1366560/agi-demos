"""Compare bytes actually served to both renderers for every installed business page."""

import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from .marketplace_browser import business_release

pytestmark = pytest.mark.integration
PACKAGES = ("agent", "automation", "billing", "environments", "knowledge", "workspace")


@pytest.fixture(scope="module")
def installations():
    owner_file = os.getenv("MEMSTACK_QA_SHARED_PAGES_OWNER")
    if not owner_file:
        pytest.skip("Requires a local QA project and tenant with the six npm packages installed")
    owner = json.loads(Path(owner_file).read_bytes())
    api = os.getenv("MEMSTACK_QA_NATIVE_API", "http://127.0.0.1:8000")
    assert urlsplit(api).hostname in {"localhost", "127.0.0.1", "::1"}
    project_id = os.getenv("MEMSTACK_QA_SHARED_PAGES_PROJECT") or owner["project_id"]
    tenant = {"tenant_id": owner["tenant_id"]}
    scopes = [
        ("/platform-plugins/v2/optional-business", {**tenant, "project_id": project_id}),
        ("/tenant-packages", tenant),
    ]
    with httpx.Client(base_url=api + "/api/v1", timeout=60) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        yield client, scopes


def render_assets(client, base, params, row, page, target):
    resource = (
        client.get(
            f"{base}/{row['plugin_id']}/ui",
            params={
                **params,
                "page_id": page["id"],
                "target": target,
                "expected_digest": row["actual_digest"],
            },
        )
        .raise_for_status()
        .json()
    )
    assert resource["release_digest"] == row["actual_digest"] and resource["target"] == target
    assert resource["id"] == page["id"] and resource["routes"] == page["routes"]
    assets = {}
    for kind in ("entry", "style", "resources"):
        records = resource.get(kind, [])
        if isinstance(records, dict):
            records = [records]
        for asset in records:
            data = base64.b64decode(asset["bytes_base64"], validate=True)
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            assert data and digest == asset["digest"], (row["plugin_id"], page["id"], target, kind)
            assets[kind, asset["path"]] = digest
    assert any(kind == "entry" for kind, _ in assets)
    return assets


@pytest.mark.parametrize("name", PACKAGES)
def test_installed_shared_page_bytes(installations, name):
    client, scopes = installations
    version = business_release(name)
    plugin = "memstack-" + name
    compared = 0
    for base, params in scopes:
        # Discover the signed target/scope declarations, including pages mounted only in slots.
        response = client.get(
            base + "/npm/detail",
            params={
                **params,
                "plugin_id": plugin,
                "package_name": "@memstack/" + name,
                "version": version,
            },
        )
        if response.status_code == 404 and "project_id" not in params:
            # Packages with exclusively project-scoped pages have no tenant marketplace entry.
            continue
        details = response.raise_for_status().json()
        release = details["release"]
        assert release and release["pages"], (name, base, details.get("release_error"))
        row = details["installation"]
        assert row and row["actual_digest"] == release["digest"], (
            name,
            base,
            version,
        )
        assert row["running_version"] == version
        pages = release["pages"]
        surfaces = {}
        for target in ("web", "desktop-renderer"):
            entries = {}
            for page in pages:
                if target not in page["targets"]:
                    continue
                # The same bookmarked route can retain older renderer-specific page IDs.
                location = tuple(sorted(page["routes"])) or (
                    "slot",
                    page.get("contributes_to") or page["id"],
                )
                assert location not in entries, (name, location, target)
                entries[location] = render_assets(client, base, params, row, page, target)
            surfaces[target] = entries
        assert surfaces["web"] == surfaces["desktop-renderer"], (name, base)
        compared += len(surfaces["web"])
    assert compared > 0
    print(f"{name} {version}: {compared} installed pages have matching signed assets")


def test_other_package_executes_during_release_switch(installations):
    """A live Wasm export continues while a different installed package changes version."""
    import csv
    from concurrent.futures import ThreadPoolExecutor
    from io import StringIO

    client, ((base, scope), _) = installations
    project = base + "/memstack-workspace"
    digest = client.get(project, params=scope).raise_for_status().json()["actual_digest"]
    package = "memstack-automation"
    current = business_release("automation")
    previous = os.getenv("MEMSTACK_QA_PREVIOUS_AUTOMATION", "1.4.4")

    def details(version):
        return (
            client.get(
                base + "/npm/detail",
                params={
                    **scope,
                    "plugin_id": package,
                    "package_name": "@memstack/automation",
                    "version": version,
                },
            )
            .raise_for_status()
            .json()
        )

    def select_release(version):
        info = details(version)
        release = info["release"]
        assert set(release["permissions"]).issubset(approved)
        return client.post(
            base + "/npm/apply",
            json={
                **scope,
                "package_name": "@memstack/automation",
                "version": version,
                "expected_revision": info["desired_revision"],
                "expected_digest": release["digest"],
                "approved_permissions": release["permissions"],
            },
        ).raise_for_status()

    def export():
        response = client.post(
            project + "/commands",
            json={
                **scope,
                "command_id": "export-csv",
                "expected_digest": digest,
                "payload": {
                    "header": True,
                    "rows": [
                        {
                            "id": "stable",
                            "name": "Across versions",
                            "office_status": "",
                            "is_archived": False,
                        }
                    ],
                },
            },
        ).raise_for_status()
        assert (
            next(iter(csv.DictReader(StringIO(response.json()["csv"]))))["name"] == "Across versions"
        )

    info = details(current)
    assert info["installation"]["actual_digest"] == info["release"]["digest"]
    approved = set(info["release"]["permissions"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            switching = pool.submit(select_release, previous)
            export()
            switching.result()
            assert details(previous)["installation"]["running_version"] == previous
            restoring = pool.submit(client.post, base + "/" + package + "/rollback", json=scope)
            export()
            restoring.result().raise_for_status()
            assert details(current)["installation"]["running_version"] == current
            export()
        finally:
            if details(current)["installation"]["running_version"] != current:
                select_release(current)
