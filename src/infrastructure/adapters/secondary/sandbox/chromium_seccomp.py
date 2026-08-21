"""Docker seccomp policy required by Chromium's user-namespace sandbox."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, cast

_PROFILE_RESOURCE = "chromium_seccomp_profile.json"
_REQUIRED_USER_NAMESPACE_SYSCALLS = frozenset({"clone", "setns", "unshare"})


@lru_cache(maxsize=1)
def _chromium_seccomp_profile_json() -> str:
    """Load and validate the bundled default-deny Chromium seccomp profile."""
    raw_profile = files(__package__).joinpath(_PROFILE_RESOURCE).read_text(encoding="utf-8")
    profile = cast("dict[str, Any]", json.loads(raw_profile))
    if profile.get("defaultAction") != "SCMP_ACT_ERRNO":
        raise RuntimeError("Chromium seccomp profile must remain default-deny")

    allowed_syscalls = {
        name
        for rule in cast("list[dict[str, Any]]", profile.get("syscalls", []))
        if rule.get("action") == "SCMP_ACT_ALLOW"
        for name in cast("list[str]", rule.get("names", []))
    }
    missing = _REQUIRED_USER_NAMESPACE_SYSCALLS - allowed_syscalls
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(f"Chromium seccomp profile is missing syscalls: {missing_names}")

    return json.dumps(profile, separators=(",", ":"), sort_keys=True)


def chromium_seccomp_security_opt() -> list[str]:
    """Return Docker's inline seccomp security option for one container create."""
    return [f"seccomp={_chromium_seccomp_profile_json()}"]
