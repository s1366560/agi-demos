"""Publish a second edition of an official page against the original execution artifacts."""

import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

from memstack_plugin_sdk.pack import build

BUSINESS = Path(__file__).resolve().parents[3] / "plugins/business"


def publish_page_revision(archive, stage, version, signer):
    package = BUSINESS / archive.stem.removeprefix("memstack-")
    metadata = json.loads((package / "package.json").read_bytes())
    stage.mkdir()
    with ZipFile(archive) as current:
        cloud = stage
        config_path = stage / "package.json"
        config = metadata
        if "targets" in metadata:
            cloud_config = Path(metadata["targets"]["python"])
            config_path = stage / cloud_config
            cloud = stage / cloud_config.parent
            cloud.mkdir(parents=True)
            config = json.loads((package / cloud_config).read_bytes())
            native_config = Path(metadata["targets"]["desktop-sidecar"])
            native = stage / native_config.parent
            native.mkdir(parents=True)
            native_spec = json.loads((package / native_config).read_bytes())
            with ZipFile(io.BytesIO(current.read("targets/desktop-sidecar.mspkg"))) as child:
                (native / "device.wasm").write_bytes(child.read("artifacts/tool.wasm"))
            (stage / native_config).write_text(json.dumps({**native_spec, "wasm": "device.wasm"}))
            (stage / "package.json").write_text(json.dumps({**metadata, "version": version}))
        if "artifacts/worker.json" in current.namelist():
            config.pop("wasm", None)
            config["worker"] = "worker.json"
            (cloud / "worker.json").write_bytes(current.read("artifacts/worker.json"))
        else:
            (cloud / config["wasm"]).write_bytes(current.read("artifacts/tool.wasm"))
        contributions = json.loads(current.read("contributions.json"))
        for slot in contributions.get("ui", []):
            path = cloud / slot["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(current.read("ui/" + slot["path"]))
        for page in contributions["pages"]:
            assets = [page["entry"]]
            if page.get("style"):
                assets.append(page["style"])
            for asset in assets:
                path = cloud / asset["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                data = current.read("pages/" + asset["path"])
                if asset == page["entry"]:
                    data += (
                        "\n;document.body.append(Object.assign(document.createElement('p'),"
                        f"{{textContent:'Publisher edition {version}'}}));"
                    ).encode()
                    asset["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
                path.write_bytes(data)
        (cloud / config["contribution"]).write_text(json.dumps(contributions))
        config_path.write_text(json.dumps({**config, "version": version}))
    return build(stage / "package.json", signer)
