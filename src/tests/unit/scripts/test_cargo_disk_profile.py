"""Exercise disk-saving Cargo defaults without installing or compiling anything."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILE_VARIABLES = ("CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG")


def _executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ("0", "1", "1")),
        (dict.fromkeys(PROFILE_VARIABLES, ""), ("0", "1", "1")),
        (
            dict(zip(PROFILE_VARIABLES, ("1", "2", "0"), strict=True)),
            ("1", "2", "0"),
        ),
    ],
)
def test_wrapper_forwards_profile_defaults_and_overrides_to_exec(
    tmp_path: Path, overrides: dict[str, str], expected: tuple[str, str, str]
) -> None:
    wrapper = tmp_path / "scripts/avernet-bcs/cargo.sh"
    wrapper.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "scripts/avernet-bcs/cargo.sh", wrapper)
    workspace = tmp_path / "third_party/avernet-bcs"
    workspace.mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    _executable(
        fake_bin / "uname",
        '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; *) exit 90;; esac\n',
    )
    _executable(
        fake_bin / "rustup",
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if sys.argv[1:] == ['toolchain', 'list']:\n"
        "    print('1.91.1-x86_64-unknown-linux-gnu')\n"
        "elif sys.argv[1:4] == ['run', '1.91.1', 'cargo']:\n"
        f"    keys = {(*PROFILE_VARIABLES, 'CARGO_TARGET_DIR', 'PROTOC')!r}\n"
        "    print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(),\n"
        "                      'env': {key: os.environ.get(key) for key in keys}}))\n"
        "else:\n"
        "    raise SystemExit('unexpected installation or toolchain command')\n",
    )
    protoc = tmp_path / ".cache/avernet-bcs/protoc/25.3/linux-x86_64/bin/protoc"
    _executable(protoc, "#!/bin/sh\nexit 91\n")
    for command in ("curl", "unzip"):
        _executable(fake_bin / command, "#!/bin/sh\nexit 92\n")
    environment = {"PATH": f"{fake_bin}{os.pathsep}{os.defpath}", "HOME": str(tmp_path)}
    environment.update(overrides)
    arguments = ["test", "-p", "memstack-workspace-core", "--locked", "--offline"]
    result = subprocess.run(
        ["/bin/bash", str(wrapper), *arguments],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    observed = json.loads(result.stdout)
    assert observed["args"] == ["run", "1.91.1", "cargo", *arguments]
    assert Path(observed["cwd"]).resolve() == workspace.resolve()
    assert tuple(observed["env"][key] for key in PROFILE_VARIABLES) == expected
    assert (
        Path(observed["env"]["CARGO_TARGET_DIR"]).resolve()
        == (tmp_path / ".cache/avernet-bcs/target").resolve()
    )
    assert Path(observed["env"]["PROTOC"]).resolve() == protoc.resolve()


def test_native_workspace_profiles_limit_local_artifacts_without_changing_release() -> None:
    manifest = tomllib.loads((REPO_ROOT / "agi-stack/Cargo.toml").read_text(encoding="utf-8"))
    for name in ("dev", "test"):
        assert manifest["profile"][name] == {"debug": 1, "incremental": False}
    assert manifest["profile"]["release"] == {
        "opt-level": "z",
        "lto": True,
        "codegen-units": 1,
        "strip": True,
        "panic": "abort",
    }
