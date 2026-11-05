"""Validate the Ray Docker context with Docker SDK's real archive filtering."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from docker.utils.build import PatternMatcher, tar

ROOT = Path(__file__).resolve().parents[4]
IGNORE = ROOT / "Dockerfile.ray.dockerignore"


def patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_ray_context_retains_global_credential_exclusions() -> None:
    assert set(patterns(ROOT / ".dockerignore")).issubset(patterns(IGNORE))


def test_docker_sdk_context_keeps_runtime_sources_and_excludes_generated_or_private_files(
    tmp_path: Path,
) -> None:
    included = [
        "Dockerfile.ray",
        "pyproject.toml",
        "uv.lock",
        "src/infrastructure/agent/actor/worker.py",
        "src/infrastructure/plugins/v2/generated/builtin.json",
        "config/provider-config.json",
        "shared/fixtures/protocol.json",
        "alembic/versions/example.py",
        "assets/fonts/example.ttf",
        "docker/ray/start-runtime.py",
        "docker/ray/check-actor-ready.py",
        "docker/ray-runtime.env",
        "scripts/example.py",
        ".env.example",
        "component/.env.example",
    ]
    excluded = [
        "agi-stack/target/debug/sidecar",
        "third_party/avernet-bcs/target/release/core",
        "component/target/output",
        "agi-stack/apps/desktop/out/main/index.js",
        "agi-stack/apps/desktop/build/cua-node-downloads/node.tar.gz",
        "agi-stack/apps/desktop/.gitnexus/parsedfile-cache/blob",
        "agi-stack/apps/desktop/sidecar/.gitnexus/lbug/blob",
        "agi-stack/apps/desktop/release/mac-arm64/MemStack.app/Contents/MacOS/MemStack",
        "agi-stack/apps/desktop/dist/client.js",
        "component/.build/release/helper",
        "component/.next/cache/bundle.js",
        "artifacts/desktop-functional-example/recording.mp4",
        ".ua/tmp/output",
        ".tmp/desktop-final-walkthrough/screenshot.png",
        "docs/development/example.md",
        "src/tests/unit/example.py",
        "tests/example.py",
        "evals/results/example.json",
        "design-prototype/example/index.html",
        "agi-stack/apps/desktop/tests/example.test.mjs",
        "agi-stack/crates/core/tests/example.rs",
        "web/src/test/example.test.ts",
        "web/e2e/example.spec.ts",
        ".cache/avernet-bcs/target/debug/core",
        "component/.cache/generated.dat",
        "logs/api.log",
        ".venv/bin/python",
        "component/.venv/bin/python",
        "component/venv/bin/python",
        "web/node_modules/vite/index.js",
        "component/node_modules/package/index.js",
        "src/__pycache__/worker.pyc",
        ".env",
        ".env.local",
        "component/.env",
        "component/.env.production",
        ".aws/credentials",
        "component/.aws/credentials",
        ".ssh/id_ed25519",
        "component/.ssh/id_ed25519",
        "secrets/token.txt",
        "component/secrets/token.txt",
        "config/private.pem",
        "component/private.key",
        "component/.netrc",
        "component/.npmrc",
        "component/.pypirc",
        "component/private.p12",
        "component/private.pfx",
        "config/value.secret.yaml",
        "config/value.tfvars",
        ".memstack/device-settings.json",
        ".memstack/vault/encrypted.json",
    ]
    for name in [*included, *excluded]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("neutral fixture", encoding="utf-8")
    with (
        tar(str(tmp_path), exclude=patterns(IGNORE), dockerfile=("Dockerfile.ray", None)) as stream,
        tarfile.open(fileobj=stream) as archive,
    ):
        names = set(archive.getnames())
    assert set(included).issubset(names)
    assert set(excluded).isdisjoint(names), set(excluded).intersection(names)


def test_ray_context_preserves_all_declared_production_module_sources() -> None:
    matcher = PatternMatcher(patterns(IGNORE))
    sources: set[str] = set()
    for path in (ROOT / "config/plugin-manifests-v2").glob("*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for module in manifest["modules"]:
            source = module["artifact"]["source"]
            if source.startswith(("repo+python://", "repo+rust://", "repo+typescript://")):
                sources.add(source.split("://", 1)[1])
    assert sources
    assert not {source for source in sources if matcher.matches(source)}
