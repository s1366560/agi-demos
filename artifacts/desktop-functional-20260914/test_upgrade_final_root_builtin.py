"""Isolated maintenance control-flow tests; no DB or account mutations."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import upgrade_final_root_builtin as maintenance

from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import parse_desired_bundle_set_v2


@pytest.mark.unit
@pytest.mark.parametrize("scenario", ["dry", "noop", "success", "cas_failure"])
async def test_root_only_maintenance_control_flow(monkeypatch, tmp_path, scenario):
    source = json.loads(Path(__file__).with_name("final-desired-recovery-dry-run.json").read_text())
    before = parse_desired_bundle_set_v2(source["scopes"][0]["before"])
    replacement = replace(before.bundles[0], digest="sha256:" + "1" * 64)
    after = replace(before, revision=before.revision + 1, bundles=(replacement,))
    after = replace(after, digest=desired_bundle_set_digest_v2(after))
    if scenario == "noop":
        before = after
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    repository = SimpleNamespace(
        current_desired_set=AsyncMock(
            side_effect=[SimpleNamespace(desired_set=before), SimpleNamespace(desired_set=after)]
        )
    )
    bootstrap = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(user_id="test-temporary-actor")),
        deactivate=AsyncMock(),
    )
    bootstrap_factory = Mock(return_value=bootstrap)
    upgrade = AsyncMock(return_value=SimpleNamespace(desired_set=after))
    if scenario == "cas_failure":
        upgrade.side_effect = ValueError("simulated concurrent CAS")
    monkeypatch.setattr(maintenance, "async_session_factory", sessions)
    monkeypatch.setattr(maintenance, "replacement_for", lambda _target: replacement)
    monkeypatch.setattr(maintenance, "production_bundle_sources_v2", lambda: object())
    monkeypatch.setattr(
        maintenance, "PlatformPluginDesiredBundleSetRepositoryV2", lambda _db: repository
    )
    monkeypatch.setattr(
        maintenance,
        "PlatformPluginProfileSourceRepositoryV2",
        lambda _db: SimpleNamespace(read_exact=AsyncMock(return_value=object())),
    )
    monkeypatch.setattr(maintenance, "BootstrapLocalPlatformAdministrator", bootstrap_factory)
    monkeypatch.setattr(
        maintenance, "SqlLocalPlatformAdministratorRepository", lambda _db: object()
    )
    monkeypatch.setattr(maintenance, "ScopedInstalledBundleLoaderV2", Mock())
    monkeypatch.setattr(maintenance, "upgrade_root_builtin_bundle_v2", upgrade)
    monkeypatch.setattr(
        maintenance,
        "get_settings",
        lambda: SimpleNamespace(
            plugin_marketplace_trusted_key_files=(),
            plugin_marketplace_allowed_registries=(),
            environment="development",
            postgres_host="localhost",
        ),
    )
    args = SimpleNamespace(
        expected_target_digest=replacement.digest,
        apply=scenario != "dry",
        output=tmp_path / "report.json",
    )
    if scenario == "cas_failure":
        with pytest.raises(ValueError, match="simulated concurrent CAS"):
            await maintenance.run(args)
    else:
        await maintenance.run(args)
    report = json.loads(args.output.read_text())
    if scenario in {"dry", "noop"}:
        bootstrap_factory.assert_not_called()
        db.commit.assert_not_awaited()
        upgrade.assert_not_awaited()
        assert report["applied"] is False
    else:
        bootstrap.deactivate.assert_awaited_once()
        assert report["temporary_identity_deactivated"]
        assert upgrade.await_args.kwargs["scope"] == maintenance.scope_for(None)
        assert upgrade.await_args.kwargs["expected_revision"] == before.revision
        assert upgrade.await_args.kwargs["expected_bundle"] == before.bundles[0]
        assert report["applied"] == (scenario == "success")
