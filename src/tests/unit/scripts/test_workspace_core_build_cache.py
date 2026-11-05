"""Exercise the Workspace Core build command and its restricted Docker context."""

from __future__ import annotations

import os
import re
import subprocess
import tarfile
from pathlib import Path

import pytest
from docker.utils.build import tar

ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = ROOT / "Dockerfile.workspace-core"
IGNORE = ROOT / "Dockerfile.workspace-core.dockerignore"


def _compile_instruction() -> str:
    instructions = DOCKERFILE.read_text().replace("\\\n", " ").splitlines()
    return next(
        line.removeprefix("RUN ") for line in instructions if "cargo build --locked" in line
    )


def _compile_command() -> str:
    return re.sub(r"^(?:--mount=\S+\s+)+", "", _compile_instruction())


def _fake_cargo(tmp_path: Path) -> dict[str, str]:
    executable = tmp_path / "bin/cargo"
    executable.parent.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> cargo.calls\n'
        '[ "${BUILD_FAIL:-0}" = 0 ] || exit 17\n'
        "mkdir -p target/release\n"
        "cp current-source target/release/memstack-workspace-core\n"
    )
    executable.chmod(0o700)
    return {**os.environ, "PATH": f"{executable.parent}:/usr/bin:/bin"}


def test_cargo_target_cache_is_locked_and_partitioned_by_architecture() -> None:
    instruction = _compile_instruction()
    assert "ARG TARGETARCH" in DOCKERFILE.read_text()
    assert (
        "--mount=type=cache,id=memstack-workspace-core-rust-1.91.1-${TARGETARCH},"
        "target=/build/avernet-bcs/target,sharing=locked"
    ) in instruction


def test_compilation_exports_fresh_binary_outside_the_reused_cache(tmp_path: Path) -> None:
    environment = _fake_cargo(tmp_path)
    source = tmp_path / "current-source"
    output = tmp_path / "out/memstack-workspace-core"
    for version in ("first source", "changed source"):
        source.write_text(version)
        subprocess.run(
            ["sh", "-ec", _compile_command()],
            cwd=tmp_path,
            env=environment,
            check=True,
            capture_output=True,
            timeout=10,
        )
        assert output.read_text() == version
        assert (tmp_path / "target/release/memstack-workspace-core").read_text() == version
    assert (tmp_path / "cargo.calls").read_text().splitlines() == [
        "build --locked --release --package memstack-workspace-core",
    ] * 2
    assert (
        "COPY --from=builder /build/avernet-bcs/out/memstack-workspace-core "
        "/usr/local/bin/memstack-workspace-core"
    ) in DOCKERFILE.read_text()


def test_failed_compilation_cannot_export_a_stale_cached_binary(tmp_path: Path) -> None:
    environment = {**_fake_cargo(tmp_path), "BUILD_FAIL": "1"}
    cached = tmp_path / "target/release/memstack-workspace-core"
    cached.parent.mkdir(parents=True)
    cached.write_text("old cached binary")
    result = subprocess.run(
        ["sh", "-ec", _compile_command()],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 17
    assert cached.read_text() == "old cached binary"
    assert not (tmp_path / "out/memstack-workspace-core").exists()


@pytest.mark.parametrize("changed", ["native.rs", "desktop_schema.sql", "Cargo.toml"])
def test_context_keeps_build_inputs_and_excludes_unrelated_or_private_files(
    tmp_path: Path, changed: str
) -> None:
    required = {
        "Dockerfile.workspace-core",
        "third_party/avernet-bcs/Cargo.toml",
        "third_party/avernet-bcs/Cargo.lock",
        f"third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/{changed}",
        "docker/workspace-core/entrypoint.sh",
        "docker/workspace-core/bcs-config.toml.template",
    }
    excluded = {
        ".env",
        "src/application/unrelated.py",
        "web/src/unrelated.tsx",
        "agi-stack/target/debug/unrelated",
        "third_party/avernet-bcs/README.md",
        "third_party/unrelated/source.rs",
        "docker/unrelated/Dockerfile",
        "docker/workspace-core/unrelated.txt",
        "third_party/avernet-bcs/crates/probe/.env",
        "third_party/avernet-bcs/crates/probe/private.key",
        "third_party/avernet-bcs/crates/probe/target/cached",
        "third_party/avernet-bcs/crates/probe/node_modules/cached.js",
    }
    for name in required | excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("neutral build fixture")
    with (
        tar(str(tmp_path), exclude=IGNORE.read_text().splitlines()) as context,
        tarfile.open(fileobj=context) as archive,
    ):
        names = set(archive.getnames())
    assert required <= names
    assert not excluded & names, sorted(excluded & names)
