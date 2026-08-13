from __future__ import annotations

import os
import platform
import shutil
import subprocess
import textwrap
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CARGO_WRAPPER = REPOSITORY_ROOT / "scripts" / "avernet-bcs" / "cargo.sh"


def _protoc_platform_key() -> str:
    system = platform.system()
    machine = platform.machine()
    keys = {
        ("Darwin", "arm64"): "osx-aarch_64",
        ("Darwin", "x86_64"): "osx-x86_64",
        ("Linux", "aarch64"): "linux-aarch_64",
        ("Linux", "arm64"): "linux-aarch_64",
        ("Linux", "x86_64"): "linux-x86_64",
        ("Linux", "amd64"): "linux-x86_64",
    }
    return keys[(system, machine)]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


def test_cargo_wrapper_bootstraps_with_the_existing_rustup_proxy_home(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    wrapper = repository_root / "scripts" / "avernet-bcs" / "cargo.sh"
    wrapper.parent.mkdir(parents=True)
    shutil.copy2(CARGO_WRAPPER, wrapper)
    bcs_root = repository_root / "third_party" / "avernet-bcs"
    bcs_root.mkdir(parents=True)
    (bcs_root / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")

    protoc = (
        repository_root
        / ".cache"
        / "avernet-bcs"
        / "protoc"
        / "25.3"
        / _protoc_platform_key()
        / "bin"
        / "protoc"
    )
    _write_executable(protoc, "#!/bin/sh\nexit 0\n")

    proxy_home = tmp_path / "rustup-proxy-home"
    fake_bin = proxy_home / "bin"
    toolchain_marker = tmp_path / "toolchain-installed"
    install_cargo_home_record = tmp_path / "install-cargo-home"
    cargo_home_record = tmp_path / "cargo-home"
    cargo_args_record = tmp_path / "cargo-args"
    _write_executable(
        fake_bin / "rustup",
        """
        #!/bin/sh
        set -eu
        case "${1:-}" in
          toolchain)
            case "${2:-}" in
              list)
                if [ -f "$FAKE_TOOLCHAIN_MARKER" ]; then
                  printf '%s\n' '1.91.1-aarch64-apple-darwin (default)'
                fi
                ;;
              install)
                printf '%s\n' "$CARGO_HOME" > "$RUSTUP_INSTALL_CARGO_HOME_RECORD"
                if [ "$CARGO_HOME" != "$EXPECTED_RUSTUP_PROXY_HOME" ]; then
                  printf '%s\n' "rustup is not installed at '$CARGO_HOME'" >&2
                  exit 1
                fi
                touch "$FAKE_TOOLCHAIN_MARKER"
                ;;
              *) exit 2 ;;
            esac
            ;;
          run)
            shift 2
            exec "$@"
            ;;
          *) exit 2 ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "cargo",
        """
        #!/bin/sh
        set -eu
        printf '%s\n' "$CARGO_HOME" > "$CARGO_HOME_RECORD"
        printf '%s\n' "$*" > "$CARGO_ARGS_RECORD"
        """,
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "EXPECTED_RUSTUP_PROXY_HOME": str(proxy_home),
            "FAKE_TOOLCHAIN_MARKER": str(toolchain_marker),
            "RUSTUP_INSTALL_CARGO_HOME_RECORD": str(install_cargo_home_record),
            "CARGO_HOME_RECORD": str(cargo_home_record),
            "CARGO_ARGS_RECORD": str(cargo_args_record),
        }
    )

    completed = subprocess.run(
        [str(wrapper), "metadata", "--format-version", "1"],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert install_cargo_home_record.read_text(encoding="utf-8").strip() == str(proxy_home)
    expected_cargo_home = repository_root / ".cache" / "avernet-bcs" / "cargo"
    assert cargo_home_record.read_text(encoding="utf-8").strip() == str(expected_cargo_home)
    assert cargo_args_record.read_text(encoding="utf-8").strip() == "metadata --format-version 1"
