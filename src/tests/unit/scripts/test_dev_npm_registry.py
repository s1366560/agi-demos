"""Development npm wrappers keep the exact bytes of a signed package."""

import base64
import hashlib
import json

import pytest

from scripts.dev import npm_registry

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("changed", [False, True])
def test_downloaded_signed_archive_must_match_the_source(tmp_path, monkeypatch, changed):
    package = npm_registry.Package("@memstack/sample", "1.0.0", b"signed archive")
    other = npm_registry.Package(package.name, package.version, b"a different signed archive")
    received = npm_registry.tarball(other if changed else package)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(received).digest()).decode()
    filename = "sample.tgz"

    def npm(args, directory):
        if args == ["view", package.selector, "dist.integrity"]:
            return json.dumps(integrity).encode()
        assert args == ["pack", package.selector]
        (directory / filename).write_bytes(received)
        return json.dumps([{"filename": filename}]).encode()

    monkeypatch.setattr(npm_registry, "npm", npm)
    if changed:
        with pytest.raises(ValueError, match="Signed archive differs"):
            npm_registry.verify(package, tmp_path)
    else:
        npm_registry.verify(package, tmp_path)


def test_registry_restart_preserves_publisher(tmp_path):
    state = tmp_path / "registry"
    npm_registry.initialize(state)
    credentials = (state / "password").read_bytes()
    approved = (state / "publishers").read_bytes()
    npm_registry.initialize(state)
    assert (state / "password").read_bytes() == credentials
    assert (state / "publishers").read_bytes() == approved
