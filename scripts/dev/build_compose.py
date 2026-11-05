#!/usr/bin/env python3
"""Build one Compose image through a host-packed stdin context instead of Desktop file RPCs."""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from docker.utils.build import tar

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from typing import BinaryIO

_SCALARS = {"target": "--target", "network": "--network", "shm_size": "--shm-size"}
_LISTS = {"cache_from": "--cache-from", "cache_to": "--cache-to", "tags": "--tag"}
_SUPPORTED = {
    "context",
    "dockerfile",
    "args",
    "platforms",
    "pull",
    "no_cache",
    "labels",
    *_SCALARS,
    *_LISTS,
}
_PRIVATE = (
    ".git",
    ".env",
    ".env.*",
    ".ssh",
    ".aws",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "secrets",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.secret.yaml",
    "*.tfvars",
)


class BuildConfigurationError(ValueError):
    """A bounded configuration diagnostic that never contains resolved values."""


@dataclass(frozen=True)
class BuildSpec:
    service: str
    image: str
    repo: Path
    context: Path
    dockerfile: str
    docker: tuple[str, ...]
    options: Mapping[str, object] = field(repr=False)
    platform: str | None = None


def resolve_build(repo: Path, service: str, compose: Sequence[str]) -> BuildSpec:
    if "compose" not in compose:
        raise BuildConfigurationError("expected docker compose command after --")
    result = subprocess.run(
        [*compose, "config", "--format", "json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise BuildConfigurationError("Compose build configuration could not be resolved")
    config: object = json.loads(result.stdout)
    if not isinstance(config, dict):
        raise BuildConfigurationError("invalid Compose configuration")
    services = config.get("services")
    selected = services.get(service) if isinstance(services, dict) else None
    if not isinstance(selected, dict):
        raise BuildConfigurationError("selected Compose service is unavailable")
    build = selected.get("build")
    image = selected.get("image")
    if not isinstance(build, dict) or not isinstance(image, str) or not image:
        raise BuildConfigurationError(
            "selected service requires an explicit image and local build context"
        )
    if set(build) - _SUPPORTED:
        raise BuildConfigurationError(
            "selected Compose build uses unsupported options; use Compose build directly"
        )
    raw_context, raw_dockerfile = build.get("context"), build.get("dockerfile", "Dockerfile")
    if not isinstance(raw_context, str) or not isinstance(raw_dockerfile, str):
        raise BuildConfigurationError("selected service requires a local context and Dockerfile")
    context = (repo / raw_context).resolve()
    dockerfile = (context / raw_dockerfile).resolve()
    if not context.is_dir() or not dockerfile.is_file() or not dockerfile.is_relative_to(context):
        raise BuildConfigurationError("Dockerfile must exist inside the local build context")
    platform = selected.get("platform")
    if platform is not None and not isinstance(platform, str):
        raise BuildConfigurationError("invalid Compose platform")
    return BuildSpec(
        service,
        image,
        repo,
        context,
        str(dockerfile.relative_to(context)),
        tuple(compose[: compose.index("compose")]),
        cast("dict[str, object]", build),
        platform,
    )


def context_patterns(spec: BuildSpec) -> list[str]:
    dedicated = spec.context / (spec.dockerfile + ".dockerignore")
    selected = dedicated if dedicated.is_file() else spec.context / ".dockerignore"
    if selected.is_file() and not selected.resolve().is_relative_to(spec.context):
        raise BuildConfigurationError("Docker ignore file must remain inside its build context")
    patterns = (
        [
            line.strip()
            for line in selected.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if selected.is_file()
        else []
    )
    # A custom Dockerfile/ignore must not accidentally upload checkout credentials.
    patterns.extend(pattern for name in _PRIVATE for pattern in (name, f"**/{name}"))
    return patterns


@contextlib.contextmanager
def packed_context(spec: BuildSpec) -> Iterator[BinaryIO]:
    # SDK preserves normal tar metadata and archives symlinks without following them.
    # Gzip is recognized before tar/PAX header probing by Docker's stdin transport.
    with tempfile.TemporaryFile() as plain, tempfile.TemporaryFile() as compressed:
        _ = tar(
            spec.context,
            exclude=context_patterns(spec),
            dockerfile=(spec.dockerfile, None),
            fileobj=plain,
        )
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=compressed, compresslevel=1, mtime=0
        ) as encoded:
            shutil.copyfileobj(plain, encoded, length=1024 * 1024)
        compressed.seek(0)
        yield compressed


def build_arguments(options: Mapping[str, object]) -> tuple[list[str], dict[str, str]]:
    command: list[str] = []
    environment = os.environ.copy()
    arguments = options.get("args", {})
    if not isinstance(arguments, dict):
        raise BuildConfigurationError("invalid Compose build arguments")
    for name, value in arguments.items():
        if not isinstance(name, str) or not name or "=" in name or "\0" in name:
            raise BuildConfigurationError("invalid Compose build argument name")
        command.extend(["--build-arg", name])
        if value is not None:
            if not isinstance(value, (str, int, float, bool)):
                raise BuildConfigurationError("invalid Compose build argument value")
            environment[name] = str(value)
    return command, environment


def list_option(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildConfigurationError("invalid Compose build option")
    return cast("list[str]", value)


def option_flags(spec: BuildSpec) -> list[str]:
    command: list[str] = []
    for key, flag in _SCALARS.items():
        value = spec.options.get(key)
        if value is not None:
            command.extend([flag, str(value)])
    for key, flag in _LISTS.items():
        for value in list_option(spec.options.get(key, [])):
            command.extend([flag, value])
    platforms = list_option(spec.options.get("platforms", []))
    if platforms or spec.platform:
        command.extend(["--platform", ",".join(platforms) if platforms else spec.platform or ""])
    labels = spec.options.get("labels", {})
    if not isinstance(labels, dict):
        raise BuildConfigurationError("invalid Compose build labels")
    for key, value in labels.items():
        command.extend(["--label", f"{key}={value}"])
    return command


def build_command(spec: BuildSpec, *, no_cache: bool = False) -> tuple[list[str], dict[str, str]]:
    arguments, environment = build_arguments(spec.options)
    command = [
        *spec.docker,
        "build",
        "--progress=plain",
        "--tag",
        spec.image,
        "--file",
        spec.dockerfile,
        *arguments,
        *option_flags(spec),
    ]
    if no_cache or spec.options.get("no_cache") is True:
        command.append("--no-cache")
    if spec.options.get("pull") is True:
        command.append("--pull")
    return [*command, "-"], environment


def build(spec: BuildSpec, *, no_cache: bool = False) -> int:
    command, environment = build_command(spec, no_cache=no_cache)
    started = time.monotonic()
    with packed_context(spec) as archive:
        packed_at = time.monotonic()
        size = archive.seek(0, os.SEEK_END)
        archive.seek(0)
        print(
            json.dumps(
                {
                    "service": spec.service,
                    "context_gzip_bytes": size,
                    "pack_seconds": round(packed_at - started, 3),
                }
            ),
            flush=True,
        )
        with subprocess.Popen(
            command, stdin=subprocess.PIPE, env=environment, cwd=spec.repo
        ) as process:
            assert process.stdin is not None
            try:
                shutil.copyfileobj(archive, process.stdin, length=1024 * 1024)
            except BrokenPipeError:
                pass
            finally:
                with contextlib.suppress(BrokenPipeError):
                    process.stdin.close()
            code = process.wait()
    print(
        json.dumps(
            {
                "service": spec.service,
                "build_exit": code,
                "total_seconds": round(time.monotonic() - started, 3),
            }
        ),
        flush=True,
    )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--service", choices=("ray-head", "memstack-workspace-core"), required=True)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("compose", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    compose = args.compose[1:] if args.compose[:1] == ["--"] else args.compose
    try:
        return build(
            resolve_build(args.repo.resolve(), args.service, compose), no_cache=args.no_cache
        )
    except BuildConfigurationError as error:
        print(f"Compose image build: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        # Config JSON/build arguments can contain credentials; never echo them.
        print(
            "Compose image build configuration or context failed; no service was started",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
