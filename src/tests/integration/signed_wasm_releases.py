"""Build two independently signed releases of a real Rust publisher package."""

import hashlib
import json
import shutil
import subprocess
import tomllib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def build_upgrade_pair(package, base, old, new, *, signer=None, page_title=None):
    from memstack_plugin_sdk.pack import build

    key = signer or Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if not shutil.which("cargo") or not shutil.which("rustup"):
        pytest.skip("publisher build requires Rust and the wasm32-unknown-unknown standard library")
    targets = subprocess.check_output(["rustup", "target", "list", "--installed"], text=True)
    if "wasm32-unknown-unknown" not in targets.splitlines():
        pytest.skip("publisher build requires the wasm32-unknown-unknown standard library")
    root = base / "release"
    shutil.copytree(package, root, ignore=shutil.ignore_patterns("target", "__pycache__", "node_modules"))
    metadata = root / "package.json" if (root / "package.json").is_file() else root / "plugin.json"
    original = build(metadata, key)
    code = root / "src/lib.rs"
    before = code.read_text()
    after = before.replace(old, new)
    assert before != after
    code.write_text(after)
    subprocess.run(
        ["cargo", "build", "--locked", "--release", "--target", "wasm32-unknown-unknown"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    crate = tomllib.loads((root / "Cargo.toml").read_text())["package"]["name"].replace("-", "_")
    destination = json.loads(metadata.read_text())["wasm"]
    shutil.copy2(root / f"target/wasm32-unknown-unknown/release/{crate}.wasm", root / destination)
    if page_title:
        contributions = root / "contributions.json"
        document = json.loads(contributions.read_bytes())
        page = root / document["ui"][0]["path"]
        page.write_text(json.dumps({**json.loads(page.read_bytes()), "title": page_title}))
        document["ui"][0]["digest"] = "sha256:" + hashlib.sha256(page.read_bytes()).hexdigest()
        contributions.write_text(json.dumps(document))
    spec = json.loads(metadata.read_text())
    major, minor, _ = spec["version"].split(".")
    metadata.write_text(json.dumps({**spec, "version": f"{major}.{int(minor) + 1}.0"}))
    return public, original, build(metadata, key)
