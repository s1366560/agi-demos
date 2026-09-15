"""No Docker/HTTP mutations: guarded QA restart failure-path tests."""

import copy
import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "qa_update", Path(__file__).with_name("update_qa_sandbox.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def container():
    return {
        "id": "old-id",
        "name": "/" + module.SANDBOX,
        "image": "old-image",
        "state": "running",
        "labels": {
            "memstack.sandbox": "true",
            "memstack.project_id": module.PROJECT,
            "memstack.tenant_id": module.TENANT,
        },
        "mounts": [
            {"Type": "bind", "Destination": "/workspace", "Source": module.WORKSPACE, "RW": True},
            {
                "Type": "volume",
                "Destination": module.CHROMIUM,
                "Name": module.CHROMIUM_VOLUME,
                "Source": "volume-path",
            },
        ],
    }


@pytest.mark.parametrize("conflict", ["label", "mount", "name", "volume"])
def test_conflicting_container_prevents_cleanup(conflict):
    original = container()
    other = copy.deepcopy(original)
    other.update(id="other-id", name="/unrelated")
    other["labels"] = {"memstack.sandbox": "true"}
    other["mounts"] = []
    if conflict == "label":
        other["labels"]["memstack.project_id"] = module.PROJECT
    elif conflict == "mount":
        other["labels"] = {}
        other["mounts"] = [original["mounts"][0]]
    elif conflict == "name":
        other["name"] = "/old-" + module.PROJECT
    else:
        other["mounts"] = [original["mounts"][1]]
    with pytest.raises(ValueError):
        module.validate_containers([original, other])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dry", "success", "timeout", "wrong_owner", "image_drift"])
async def test_official_restart_is_single_attempt_and_always_signs_out(monkeypatch, tmp_path, mode):
    before = container()
    after = copy.deepcopy(before)
    after.update(id="new-id", image=module.IMAGE)
    calls = []
    state = {"restarted": False}
    monkeypatch.setattr(module, "REPORT", tmp_path / "report.json")
    monkeypatch.setenv("QA_OWNER_PASSWORD", "test-only-not-a-credential")
    monkeypatch.setattr(
        module, "inspect_containers", lambda: [after if state["restarted"] else before]
    )

    def docker(*args):
        if args[0] == "image":
            return "drift" if mode == "image_drift" else module.IMAGE
        return '{"tool":"write","meta":{"memstack/workspace-write":{"contract":"directory-fd-write-v1","workspace_root":"/workspace"}}}'

    monkeypatch.setattr(module, "docker", docker)
    payload = {
        "sandbox_id": module.SANDBOX,
        "project_id": module.PROJECT,
        "tenant_id": module.TENANT,
        "status": "running",
        "is_healthy": True,
    }

    def handle(request):
        path = request.url.path
        calls.append((request.method, path))
        if path.endswith("/auth/token"):
            data = {"access_token": "test-only-token"}
        elif path.endswith("/auth/me"):
            data = {"user_id": "other" if mode == "wrong_owner" else module.OWNER}
        elif path.endswith("/restart"):
            state["restarted"] = True
            if mode == "timeout":
                raise httpx.ReadTimeout("private upstream detail", request=request)
            data = {"success": True, "sandbox": payload}
        elif path.endswith("/signout"):
            data = {}
        else:
            data = payload
        return httpx.Response(200, json=data)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle)),
    )
    if mode in {"timeout", "wrong_owner", "image_drift"}:
        with pytest.raises((httpx.ReadTimeout, ValueError)):
            await module.run(mode != "dry")
    else:
        await module.run(mode != "dry")
    restart = [value for value in calls if value[1].endswith("/restart")]
    assert len(restart) == (1 if mode in {"success", "timeout"} else 0)
    assert any(path.endswith("/signout") for _, path in calls) == (mode != "image_drift")
    text = (tmp_path / "report.json").read_text()
    assert "test-only-token" not in text and "private upstream detail" not in text
