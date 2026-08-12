from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_policy_module() -> ModuleType:
    repository_root = Path(__file__).resolve().parents[4]
    script_path = repository_root / "scripts" / "avernet-bcs" / "check-license-policy.py"
    spec = importlib.util.spec_from_file_location("avernet_license_policy", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reviewed_npm_override_requires_matching_license_hash(tmp_path: Path) -> None:
    module = _load_policy_module()
    license_path = tmp_path / "licenses" / "dependency.LICENSE"
    license_path.parent.mkdir()
    license_path.write_text("reviewed license\n", encoding="utf-8")
    overrides = {
        "dependency@1.2.3": {
            "expression": "MIT",
            "license_file": "licenses/dependency.LICENSE",
            "license_sha256": hashlib.sha256(license_path.read_bytes()).hexdigest(),
            "source": "https://example.test/dependency/LICENSE",
        }
    }
    errors: list[str] = []

    expression = module._reviewed_license_expression(
        tmp_path,
        {"MIT"},
        overrides,
        "dependency",
        "1.2.3",
        errors,
    )

    assert expression == "MIT"
    assert errors == []

    license_path.write_text("tampered\n", encoding="utf-8")
    expression = module._reviewed_license_expression(
        tmp_path,
        {"MIT"},
        overrides,
        "dependency",
        "1.2.3",
        errors,
    )

    assert expression is None
    assert errors == [
        "npm override:dependency@1.2.3: reviewed license hash differs: "
        f"expected={overrides['dependency@1.2.3']['license_sha256']!r} "
        f"actual={hashlib.sha256(license_path.read_bytes()).hexdigest()!r}"
    ]


def test_locked_package_name_preserves_scoped_package() -> None:
    module = _load_policy_module()

    assert module._locked_package_name("node_modules/plain", {}) == "plain"
    assert (
        module._locked_package_name(
            "node_modules/parent/node_modules/@scope/dependency",
            {},
        )
        == "@scope/dependency"
    )
    assert module._locked_package_name("test/fixtures/local", {"name": "local"}) == "local"
