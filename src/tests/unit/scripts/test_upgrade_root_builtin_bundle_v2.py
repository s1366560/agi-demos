"""Decision-logic tests for the builtin bundle reference maintenance script."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/upgrade_root_builtin_bundle_v2.py"
SPEC = importlib.util.spec_from_file_location("upgrade_root_builtin_bundle_v2", SCRIPT)
assert SPEC and SPEC.loader
upgrade_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade_script)

REPLACEMENT = BundleReferenceV2(
    bundle_id="memstack-platform-base",
    version="2.0.0",
    digest="sha256:new",
    source="builtin://memstack-platform-base/2.0.0",
)
OLD_REFERENCE = replace(REPLACEMENT, digest="sha256:old")


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeRepository:
    def __init__(self, record: object) -> None:
        self._record = record

    async def current_desired_set(self, scope: object) -> object:
        return self._record


@dataclass
class Harness:
    session: FakeSession
    engine: FakeEngine
    upgrade_calls: list[dict[str, Any]]

    def install(self, monkeypatch: pytest.MonkeyPatch, record: object) -> None:
        def factory() -> Any:
            @contextlib.asynccontextmanager
            async def enter() -> AsyncIterator[object]:
                yield self.session

            return enter()

        async def upgrade(
            session: object,
            *,
            sources: object,
            load_verified_bundle: object,
            expected_revision: int,
            expected_bundle: object,
            actor_id: str | None,
            scope: object,
            upgrade_profile_baseline: bool = False,
            expected_profile_source: object = None,
        ) -> object:
            self.upgrade_calls.append(
                {
                    "expected_revision": expected_revision,
                    "expected_bundle": expected_bundle,
                    "actor_id": actor_id,
                    "scope": scope,
                    "upgrade_profile_baseline": upgrade_profile_baseline,
                    "expected_profile_source": expected_profile_source,
                }
            )
            return SimpleNamespace(desired_set=SimpleNamespace(revision=expected_revision + 1))

        monkeypatch.setattr(upgrade_script, "async_session_factory", factory)
        monkeypatch.setattr(upgrade_script, "engine", self.engine)
        monkeypatch.setattr(
            upgrade_script,
            "production_bundle_sources_v2",
            lambda: SimpleNamespace(desired_set=SimpleNamespace(bundles=(REPLACEMENT,))),
        )
        monkeypatch.setattr(
            upgrade_script,
            "PlatformPluginDesiredBundleSetRepositoryV2",
            lambda _session: FakeRepository(record),
        )
        monkeypatch.setattr(upgrade_script, "upgrade_root_builtin_bundle_v2", upgrade)
        monkeypatch.setattr(upgrade_script, "ScopedInstalledBundleLoaderV2", _fake_loader)


def _fake_loader(**_kwargs: object) -> object:
    return object()


def desired_record(reference: BundleReferenceV2, revision: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        desired_set=SimpleNamespace(
            revision=revision,
            bundles=(reference,),
            profile_source=SimpleNamespace(
                source_id="memstack-root-initialized-profile-source-v2",
                revision=1,
                digest="sha256:oldprofile",
            ),
        )
    )


def make_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "apply": False,
        "auto": False,
        "scope_kind": "root",
        "tenant_id": None,
        "project_id": None,
        "session_id": None,
        "all_initialized_scopes": False,
        "expected_revision": None,
        "expected_digest": None,
        "upgrade_profile_baseline": False,
        "expected_source_revision": None,
        "expected_source_digest": None,
        "actor_id": None,
        "trusted_public_key": [],
        "allowed_registry": [],
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def harness() -> Harness:
    return Harness(session=FakeSession(), engine=FakeEngine(), upgrade_calls=[])


async def test_auto_upgrades_stale_reference_with_observed_values(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.install(monkeypatch, desired_record(OLD_REFERENCE, revision=7))

    await upgrade_script.run(make_args(auto=True, actor_id="make:plugin-bundle-upgrade"))

    assert len(harness.upgrade_calls) == 1
    call = harness.upgrade_calls[0]
    assert call["expected_revision"] == 7
    assert call["expected_bundle"] == OLD_REFERENCE
    assert call["actor_id"] == "make:plugin-bundle-upgrade"
    assert harness.session.commits == 1
    assert harness.engine.disposed is True
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["old_digest"] == OLD_REFERENCE.digest
    assert lines[0]["new_digest"] == REPLACEMENT.digest
    assert lines[1] == {"upgraded_desired_revision": 8}


async def test_auto_reports_up_to_date_without_writing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.install(monkeypatch, desired_record(REPLACEMENT, revision=7))

    await upgrade_script.run(make_args(auto=True, actor_id="make:plugin-bundle-upgrade"))

    assert harness.upgrade_calls == []
    assert harness.session.commits == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[1] == {"status": "up-to-date"}


async def test_auto_skips_uninitialized_scope(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.install(monkeypatch, None)

    await upgrade_script.run(make_args(auto=True, actor_id="make:plugin-bundle-upgrade"))

    assert harness.upgrade_calls == []
    assert json.loads(capsys.readouterr().out) == {"status": "uninitialized-scope"}


@pytest.mark.parametrize(
    "reference",
    [
        replace(OLD_REFERENCE, bundle_id="owned-custom-bundle"),
        replace(OLD_REFERENCE, source="oci://owned.example/custom-baseline"),
    ],
)
async def test_auto_preserves_scopes_without_the_default_builtin_reference(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reference: BundleReferenceV2,
) -> None:
    harness.install(monkeypatch, desired_record(reference))

    await upgrade_script.run(make_args(auto=True, actor_id="ops"))

    assert harness.upgrade_calls == []
    assert harness.session.commits == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "skipped",
        "reason_code": "builtin_reference_absent",
    }


async def test_explicit_missing_builtin_reference_still_rejects(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.install(monkeypatch, desired_record(replace(OLD_REFERENCE, bundle_id="owned-custom")))

    with pytest.raises(ValueError, match="builtin reference"):
        await upgrade_script.run(make_args())

    assert harness.upgrade_calls == []
    assert harness.session.commits == 0


async def test_inspect_without_auto_still_requires_initialized_scope(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.install(monkeypatch, None)

    with pytest.raises(ValueError, match="scope has not been initialized"):
        await upgrade_script.run(make_args())


async def test_apply_still_rejects_unexpected_digest(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.install(monkeypatch, desired_record(OLD_REFERENCE, revision=7))

    with pytest.raises(ValueError, match="explicitly expected old digest"):
        await upgrade_script.run(
            make_args(
                apply=True,
                expected_revision=7,
                expected_digest="sha256:something-else",
                actor_id="ops",
            )
        )

    assert harness.upgrade_calls == []


def test_cli_rejects_auto_combined_with_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--auto", "--apply", "--actor-id", "ops"])

    with pytest.raises(SystemExit) as excinfo:
        upgrade_script.main()

    assert excinfo.value.code == 2


def test_cli_requires_actor_for_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--auto"])

    with pytest.raises(SystemExit) as excinfo:
        upgrade_script.main()

    assert excinfo.value.code == 2


def test_cli_rejects_auto_with_explicit_expected_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["prog", "--auto", "--actor-id", "ops", "--expected-digest", "sha256:x"]
    )

    with pytest.raises(SystemExit) as excinfo:
        upgrade_script.main()

    assert excinfo.value.code == 2


async def test_explicit_baseline_mode_upgrades_source_even_when_builtin_digest_is_current(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record = desired_record(REPLACEMENT)
    harness.install(monkeypatch, record)
    source = SimpleNamespace(
        source_id=record.desired_set.profile_source.source_id,
        revision=1,
        digest="sha256:oldprofile",
        layers=(SimpleNamespace(layer_id="operator-overrides"),),
    )

    async def read_source(**_kwargs):
        return source

    monkeypatch.setattr(
        upgrade_script,
        "PlatformPluginProfileSourceRepositoryV2",
        lambda _session: SimpleNamespace(read_exact=read_source),
    )
    monkeypatch.setattr(
        upgrade_script,
        "production_bundle_sources_v2",
        lambda: SimpleNamespace(
            desired_set=SimpleNamespace(bundles=(REPLACEMENT,)), profile_source=object()
        ),
    )
    monkeypatch.setattr(
        upgrade_script,
        "upgrade_production_profile_baseline_v2",
        lambda *_args: SimpleNamespace(revision=2, digest="sha256:newprofile"),
    )
    await upgrade_script.run(make_args(auto=True, upgrade_profile_baseline=True, actor_id="ops"))
    assert harness.session.commits == 1
    assert harness.upgrade_calls[0]["upgrade_profile_baseline"] is True
    assert harness.upgrade_calls[0]["expected_profile_source"] == record.desired_set.profile_source
    receipt = json.loads(capsys.readouterr().out.splitlines()[0])["profile_baseline"]
    assert receipt["preserved_overlay_layers"] == ["operator-overrides"]
    assert (receipt["old_revision"], receipt["new_revision"]) == (1, 2)


async def test_batch_upgrades_each_initialized_scope_explicitly_and_commits_per_owner(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.install(monkeypatch, desired_record(OLD_REFERENCE))
    scopes = (
        ScopeV2(kind=ScopeKindV2.ROOT),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-1"),
        ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant-1", project_id="project-1"),
    )

    async def list_scopes(self):
        return scopes

    monkeypatch.setattr(FakeRepository, "list_initialized_scopes", list_scopes, raising=False)
    await upgrade_script.run(make_args(auto=True, all_initialized_scopes=True, actor_id="ops"))
    assert [call["scope"] for call in harness.upgrade_calls] == list(scopes)
    assert harness.session.commits == 3


async def test_batch_auto_continues_after_a_custom_scope_without_replacing_it(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.install(monkeypatch, desired_record(OLD_REFERENCE))
    scopes = (
        ScopeV2(kind=ScopeKindV2.ROOT),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="custom-tenant"),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="builtin-tenant"),
    )

    async def list_scopes(self):
        return scopes

    async def current(self, scope):
        reference = (
            replace(OLD_REFERENCE, bundle_id="owned-custom")
            if scope.tenant_id == "custom-tenant"
            else OLD_REFERENCE
        )
        return desired_record(reference)

    monkeypatch.setattr(FakeRepository, "list_initialized_scopes", list_scopes, raising=False)
    monkeypatch.setattr(FakeRepository, "current_desired_set", current)
    await upgrade_script.run(make_args(auto=True, all_initialized_scopes=True, actor_id="ops"))

    assert [call["scope"] for call in harness.upgrade_calls] == [scopes[0], scopes[2]]
    assert harness.session.commits == 2
    receipts = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {"status": "skipped", "reason_code": "builtin_reference_absent"} in receipts


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "--apply",
            "--upgrade-profile-baseline",
            "--actor-id",
            "ops",
            "--expected-revision",
            "1",
            "--expected-digest",
            "sha256:old",
        ],
        ["--all-initialized-scopes", "--tenant-id", "tenant-1"],
        ["--expected-source-revision", "1"],
    ],
)
def test_cli_rejects_incomplete_or_ambiguous_baseline_maintenance(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", *arguments])
    with pytest.raises(SystemExit) as caught:
        upgrade_script.main()
    assert caught.value.code == 2
