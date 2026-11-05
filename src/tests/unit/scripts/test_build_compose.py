"""Exercise the streaming build helper with real Docker SDK tar and a neutral CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/dev/build_compose.py"


@pytest.fixture
def context(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    files = {
        "Dockerfile.ray": "FROM scratch\nCOPY . /app\n",
        "Dockerfile.workspace-core": "FROM scratch\nCOPY . /app\n",
        ".dockerignore": "fallback-only\n",
        "Dockerfile.ray.dockerignore": "ignored\n",
        "Dockerfile.workspace-core.dockerignore": "ignored\n",
        "src/app.py": "neutral source",
        "uv.lock": "neutral lock",
        "pyproject.toml": "neutral declaration",
        "ignored/blob": "excluded",
        "fallback-only": "included by dedicated ignore",
        ".env": "NEUTRAL_SECRET",
        ".git/config": "NEUTRAL_SECRET",
    }
    for name, value in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)
    fake = tmp_path / "fake_docker.py"
    fake.write_text("""import io,json,os,sys,tarfile
from pathlib import Path
args=sys.argv[1:]
if "compose" in args:
 print(Path(os.environ["FIXTURE_CONFIG"]).read_text());raise SystemExit(0)
raw=sys.stdin.buffer.read()
with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as archive:
 names=archive.getnames();source=archive.extractfile("src/app.py").read().decode();lock=archive.extractfile("uv.lock").read().decode()
 links=[m.name for m in archive if m.issym()]
Path(os.environ["FIXTURE_RESULT"]).write_text(json.dumps({"argv":args,"names":names,"source":source,"lock":lock,"links":links,"arg":os.getenv("PRIVATE_BUILD_ARG"),"magic":raw[:2].hex(),"cwd":os.getcwd()}))
raise SystemExit(int(os.getenv("FIXTURE_BUILD_EXIT","0")))
""")
    return repo, fake, tmp_path / "result.json"


def invoke(context, service: str, *, options: dict | None = None, code: int = 0):
    repo, fake, result = context
    dockerfile = "Dockerfile.ray" if service == "ray-head" else "Dockerfile.workspace-core"
    build = {
        "context": str(repo),
        "dockerfile": dockerfile,
        "args": {"PRIVATE_BUILD_ARG": "NEUTRAL_PRIVATE_VALUE"},
        "target": "runtime",
    }
    build.update(options or {})
    config = repo.parent / "compose.json"
    config.write_text(
        json.dumps({"services": {service: {"image": "neutral/runtime:fixture", "build": build}}})
    )
    environment = os.environ.copy()
    environment.update(
        FIXTURE_CONFIG=str(config), FIXTURE_RESULT=str(result), FIXTURE_BUILD_EXIT=str(code)
    )
    run = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--service",
            service,
            "--",
            sys.executable,
            str(fake),
            "--context",
            "neutral-context",
            "compose",
            "-f",
            "custom.yaml",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return run, json.loads(result.read_text()) if result.exists() else None


@pytest.mark.parametrize("service", ["ray-head", "memstack-workspace-core"])
def test_streams_dedicated_ignored_archive_and_preserves_build_overrides(context, service: str):
    run, result = invoke(context, service)
    assert run.returncode == 0, run.stderr
    assert result["magic"] == "1f8b"
    assert result["cwd"] == str(context[0])
    assert result["argv"][:3] == ["--context", "neutral-context", "build"]
    assert result["argv"][-1] == "-"
    assert "neutral/runtime:fixture" in result["argv"]
    assert result["arg"] == "NEUTRAL_PRIVATE_VALUE"
    assert "NEUTRAL_PRIVATE_VALUE" not in " ".join(result["argv"])
    assert "NEUTRAL_PRIVATE_VALUE" not in run.stdout + run.stderr
    assert "src/app.py" in result["names"] and "uv.lock" in result["names"]
    assert "fallback-only" in result["names"]
    assert "ignored/blob" not in result["names"]
    assert ".env" not in result["names"] and ".git/config" not in result["names"]


def test_every_build_observes_current_source_and_dependency_bytes(context):
    assert invoke(context, "ray-head")[0].returncode == 0
    (context[0] / "src/app.py").write_text("changed source")
    (context[0] / "uv.lock").write_text("changed lock")
    run, result = invoke(context, "ray-head")
    assert run.returncode == 0
    assert result["source"] == "changed source"
    assert result["lock"] == "changed lock"


def test_build_failure_is_not_reported_as_success(context):
    run, _ = invoke(context, "ray-head", code=17)
    assert run.returncode == 17


def test_unsupported_configuration_fails_without_executing_build(context):
    run, result = invoke(context, "ray-head", options={"additional_contexts": {"other": "private"}})
    assert run.returncode != 0
    assert result is None
    assert "private" not in run.stdout + run.stderr


def test_external_symlink_is_archived_as_link_without_following_it(context):
    outside = context[0].parent / "outside-private.txt"
    outside.write_text("NEUTRAL_OUTSIDE_VALUE")
    (context[0] / "source-link").symlink_to(outside)
    run, result = invoke(context, "ray-head")
    assert run.returncode == 0
    assert "source-link" in result["links"]
    assert "outside-private.txt" not in result["names"]


def test_dockerfile_symlink_cannot_upload_outside_context(context):
    dockerfile = context[0] / "Dockerfile.ray"
    dockerfile.unlink()
    outside = context[0].parent / "outside-private.txt"
    outside.write_text("NEUTRAL_OUTSIDE_VALUE")
    dockerfile.symlink_to(outside)
    run, result = invoke(context, "ray-head")
    assert run.returncode != 0
    assert result is None


def test_ignore_symlink_cannot_read_outside_context(context):
    ignore = context[0] / "Dockerfile.ray.dockerignore"
    ignore.unlink()
    outside = context[0].parent / "outside-private.txt"
    outside.write_text("NEUTRAL_OUTSIDE_VALUE")
    ignore.symlink_to(outside)
    run, result = invoke(context, "ray-head")
    assert run.returncode != 0
    assert result is None


def test_global_ignore_is_used_when_no_dedicated_ignore_exists(context):
    (context[0] / "Dockerfile.ray.dockerignore").unlink()
    run, result = invoke(context, "ray-head")
    assert run.returncode == 0
    assert "fallback-only" not in result["names"]


def test_scalar_list_platform_and_cache_overrides_are_preserved(context):
    run, result = invoke(
        context,
        "ray-head",
        options={
            "network": "host",
            "platforms": ["linux/arm64"],
            "no_cache": True,
            "pull": True,
            "cache_from": ["type=local,src=neutral-cache"],
            "cache_to": ["type=local,dest=neutral-cache"],
            "labels": {"fixture": "neutral"},
            "tags": ["neutral/second:tag"],
        },
    )
    assert run.returncode == 0
    for value in [
        "--network",
        "host",
        "--platform",
        "linux/arm64",
        "--no-cache",
        "--pull",
        "type=local,src=neutral-cache",
        "type=local,dest=neutral-cache",
        "fixture=neutral",
        "neutral/second:tag",
    ]:
        assert value in result["argv"]


@pytest.mark.parametrize(
    "options",
    [
        {"args": ["invalid"]},
        {"args": {"invalid=name": "neutral"}},
        {"args": {"VALUE": []}},
        {"platforms": "invalid"},
        {"labels": []},
        {"cache_from": [1]},
        {"context": "/not-a-real-build-context"},
    ],
)
def test_invalid_build_config_does_not_execute_or_log_values(context, options):
    run, result = invoke(context, "ray-head", options=options)
    assert run.returncode != 0
    assert result is None
    assert "NEUTRAL_PRIVATE_VALUE" not in run.stdout + run.stderr
