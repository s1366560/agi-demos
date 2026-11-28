"""Single-package publishers need only that release's inputs."""

import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import build_standard_packages

pytestmark = pytest.mark.unit


def test_build_workspace_without_other_workers(tmp_path, monkeypatch):
    key = tmp_path / "key"
    signer = Ed25519PrivateKey.generate()
    key.write_bytes(
        signer.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    archives = tmp_path / "archives"
    monkeypatch.setattr(
        "sys.argv", ["publish", "--package", "workspace", "--key", str(key), "--out", str(archives)]
    )
    build_standard_packages.main()
    (archive,) = archives.iterdir()
    assert archive.name == "memstack-workspace.mspkg"
    with zipfile.ZipFile(archive) as signed:
        assert signed.testzip() is None
