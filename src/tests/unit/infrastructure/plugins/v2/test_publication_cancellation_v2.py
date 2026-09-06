"""Real-effect cancellation across candidate and committed host publication boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

import pytest

from src.domain.model.plugins.generated_v2 import ApplyStatusV2
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.runtime import LoaderV2, PluginDefinitionV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import _envelope, _snapshot


def _host(provider: Callable, consumer: Callable) -> PlatformPluginRuntimeHostV2:
    snapshot = _snapshot()
    modules = {
        module.module_ref: module for manifest in snapshot.manifests for module in manifest.modules
    }
    definitions = [
        PluginDefinitionV2(
            module_ref=ref,
            contract_digest=modules[ref].contract_digest,
            apply=apply,
        )
        for ref, apply in [
            ("builtin://conformance/root-provider", provider),
            ("builtin://conformance/session-consumer", consumer),
        ]
    ]
    return PlatformPluginRuntimeHostV2(
        loader=LoaderV2(
            definitions,
            target_catalog=target_catalog_from_snapshot_v2(snapshot),
            artifact_resolver=RuntimeTestArtifactResolverV2(),
        )
    )


def _contains(error: BaseException, expected: BaseException) -> bool:
    return error is expected or (
        isinstance(error, BaseExceptionGroup)
        and any(_contains(child, expected) for child in error.exceptions)
    )


@pytest.mark.unit
async def test_committed_retirement_cancellation_keeps_host_identity_and_drains_old_effects() -> (
    None
):
    first = True
    cancellation = asyncio.CancelledError("old effect cancelled itself")
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    disposed: list[str] = []

    def provider(context, _config):
        old = first
        context.provide("service:clock", 7)

        async def cleanup():
            if old:
                cleanup_entered.set()
                await cleanup_release.wait()
                disposed.append("old-provider")
            else:
                disposed.append("new-provider")

        return cleanup

    def consumer(context, _config):
        old = first
        context.require("clock")

        def cleanup():
            disposed.append("old-consumer" if old else "new-consumer")
            if old:
                raise cancellation

        return cleanup

    host = _host(provider, consumer)
    snapshot = _snapshot()
    await host.apply(snapshot, _envelope(snapshot, 1))
    old = host.manager.current
    first = False
    candidate = replace(snapshot, generation=snapshot.generation + 1, digest="2" * 64)
    publication = await host.apply(candidate, _envelope(candidate, 2))
    assert publication.receipt.status == ApplyStatusV2.ACK
    assert host.manager.current is not old
    assert host.reconciler.applied_version == 2
    assert host.reconciler.applied_digest == candidate.digest
    assert host.current_publication is publication
    assert host.current_distribution.snapshot is candidate
    assert host.current_distribution.descriptor == host.manager.current.descriptor
    await asyncio.wait_for(cleanup_entered.wait(), timeout=2)
    closing = asyncio.create_task(host.close())
    await asyncio.sleep(0)
    assert not closing.done()
    cleanup_release.set()
    await closing
    assert any(
        diagnostic.generation is old and _contains(diagnostic.error, cancellation)
        for diagnostic in host.manager.retirement_diagnostics
    )
    assert set(disposed) == {"old-consumer", "old-provider", "new-consumer", "new-provider"}


@pytest.mark.unit
async def test_external_candidate_stage_cancellation_cleans_effects_without_publication() -> None:
    entered = asyncio.Event()
    disposed: list[str] = []

    def provider(context, _config):
        context.provide("service:clock", 7)
        return lambda: disposed.append("provider")

    async def consumer(context, _config):
        context.require("clock")
        await context.effect(lambda: lambda: disposed.append("consumer"), label="before-cancel")
        entered.set()
        await asyncio.Event().wait()

    host = _host(provider, consumer)
    snapshot = _snapshot()
    applying = asyncio.create_task(host.apply(snapshot, _envelope(snapshot, 1)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    applying.cancel()
    with pytest.raises(asyncio.CancelledError):
        await applying
    assert disposed == ["consumer", "provider"]
    assert host.manager.current is None
    assert host.current_distribution is None
    assert host.current_publication is None
    assert host.reconciler.applied_version is None
    await host.close()


@pytest.mark.unit
async def test_companion_commit_failure_rolls_back_candidate_and_preserves_host_distribution() -> (
    None
):
    disposed: list[str] = []
    rollback: list[str] = []

    def provider(context, _config):
        context.provide("service:clock", 7)
        return lambda: disposed.append("provider")

    def consumer(context, _config):
        context.require("clock")
        return lambda: disposed.append("consumer")

    host = _host(provider, consumer)
    snapshot = _snapshot()
    previous_publication = await host.apply(snapshot, _envelope(snapshot, 1))
    previous = host.manager.current
    previous_distribution = host.current_distribution
    candidate = replace(snapshot, generation=snapshot.generation + 1, digest="3" * 64)

    async def prepare(_generation):
        def commit():
            raise ValueError("companion commit refused")

        return PreparedGenerationPublicationV2(
            commit=commit, rollback=lambda: rollback.append("rollback")
        )

    publication = await host.apply(candidate, _envelope(candidate, 2), publication_stager=prepare)
    assert publication.receipt.status == ApplyStatusV2.NACK
    assert publication.receipt.error_code == "publication_commit_failed"
    assert rollback == ["rollback"]
    assert disposed == ["consumer", "provider"]
    assert host.manager.current is previous
    assert host.current_distribution is previous_distribution
    assert host.current_publication is previous_publication
    assert host.reconciler.applied_version == 1
    assert host.reconciler.applied_digest == snapshot.digest
    await host.close()


@pytest.mark.unit
async def test_host_close_clears_publication_when_current_effect_cancels_itself() -> None:
    cancellation = asyncio.CancelledError("current cleanup cancelled itself")
    disposed: list[str] = []

    def provider(context, _config):
        context.provide("service:clock", 7)
        return lambda: disposed.append("provider")

    def consumer(context, _config):
        context.require("clock")

        def cleanup():
            disposed.append("consumer")
            raise cancellation

        return cleanup

    host = _host(provider, consumer)
    snapshot = _snapshot()
    await host.apply(snapshot, _envelope(snapshot, 1))
    with pytest.raises(BaseException) as error:
        await host.close()
    assert _contains(error.value, cancellation)
    assert disposed == ["consumer", "provider"]
    assert host.manager.current is None
    assert host.current_distribution is None
    assert host.current_publication is None


@pytest.mark.unit
async def test_cancelled_close_waiting_for_lock_cannot_retire_new_publication() -> None:
    disposed: list[str] = []
    label = "old"

    def provider(context, _config):
        captured = label
        context.provide("service:clock", 7)
        return lambda: disposed.append(captured + "-provider")

    def consumer(context, _config):
        captured = label
        context.require("clock")
        return lambda: disposed.append(captured + "-consumer")

    host = _host(provider, consumer)
    snapshot = _snapshot()
    await host.apply(snapshot, _envelope(snapshot, 1))
    old = host.manager.current
    label = "new"
    candidate = await host.loader.stage(
        replace(snapshot, generation=snapshot.generation + 1, digest="4" * 64)
    )
    publisher_entered = asyncio.Event()

    async def publish_new():
        publisher_entered.set()
        return await host.manager.publish(candidate)

    # Use the manager's real FIFO lock. Publication queues first; close captures the
    # currently visible old generation before its owned cleanup can acquire that lock.
    await host.manager._lock.acquire()
    publishing = asyncio.create_task(publish_new())
    await publisher_entered.wait()
    closing = asyncio.create_task(host.manager.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not closing.done()
    closing.cancel()
    host.manager._lock.release()
    await publishing
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert host.manager.current is candidate
    assert not candidate._retired
    assert not candidate._disposed
    assert old is not None and old._disposed
    assert disposed == ["old-consumer", "old-provider"]
    await host.manager.close()
    assert disposed == ["old-consumer", "old-provider", "new-consumer", "new-provider"]
