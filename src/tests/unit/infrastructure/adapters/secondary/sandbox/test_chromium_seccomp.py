"""Chromium user-namespace seccomp policy tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.infrastructure.adapters.secondary.sandbox.chromium_seccomp import (
    chromium_seccomp_security_opt,
)


def test_profile_is_default_deny_multi_arch_and_matches_image_policy() -> None:
    option = chromium_seccomp_security_opt()
    assert len(option) == 1
    prefix, serialized = option[0].split("=", maxsplit=1)
    assert prefix == "seccomp"

    profile = json.loads(serialized)
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    assert {"SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"} <= set(profile["architectures"])
    allowed = {
        name
        for rule in profile["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for name in rule["names"]
    }
    assert {"clone", "setns", "unshare"} <= allowed

    repository_root = Path(__file__).resolve().parents[7]
    image_profile = json.loads(
        (repository_root / "sandbox-mcp-server/docker/seccomp-profile.json").read_text()
    )
    assert profile == image_profile
