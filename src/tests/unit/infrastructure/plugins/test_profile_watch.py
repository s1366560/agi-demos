"""Unit tests for the profile hot-reload watcher (P4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from src.infrastructure.plugins.profile_watch import ProfileWatcher

_PROFILE = {
    "schemaVersion": 1,
    "profile": {
        "id": "watch-profile",
        "layers": [
            {
                "id": "base",
                "plugins": [
                    {"id": "workspace-runtime"},
                    {"id": "sisyphus-runtime"},
                ],
            }
        ],
    },
}


def _write(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _watcher(tmp_path: Path, **kwargs: object) -> tuple[ProfileWatcher, Path, Path]:
    profile = tmp_path / "profile.yaml"
    overlay = tmp_path / "overlay.yaml"
    _write(profile, _PROFILE)
    _write(overlay, {"patches": []})
    watcher = ProfileWatcher(profile, (overlay,), **kwargs)  # type: ignore[arg-type]
    return watcher, profile, overlay


@pytest.mark.unit
async def test_unchanged_files_produce_no_event(tmp_path: Path) -> None:
    watcher, _, _ = _watcher(tmp_path)

    assert await watcher.poll_once() is None
    assert await watcher.poll_once() is None


@pytest.mark.unit
async def test_change_applies_new_version(tmp_path: Path) -> None:
    applied: list[tuple[int, str]] = []
    watcher, _, overlay = _watcher(
        tmp_path,
        on_applied=lambda envelope, snapshot: applied.append(
            (envelope.version, snapshot.digest)
        ),
    )
    assert await watcher.poll_once() is None  # baseline

    _write(overlay, {"patches": [{"target": "sisyphus-runtime", "remove": True}]})
    event = await watcher.poll_once()

    assert event is not None and event.kind == "applied"
    assert event.version == 1
    assert applied and applied[0][0] == 1
    assert watcher.last_good is not None
    assert [row.manifest.id for row in watcher.last_good.rows] == ["workspace-runtime"]


@pytest.mark.unit
async def test_rejected_change_keeps_last_good(tmp_path: Path) -> None:
    rejected: list[str] = []
    watcher, profile, overlay = _watcher(
        tmp_path,
        on_rejected=lambda event: rejected.append(event.message or ""),
    )
    assert await watcher.poll_once() is None  # baseline
    _write(overlay, {"patches": [{"target": "sisyphus-runtime", "remove": True}]})
    first = await watcher.poll_once()
    assert first is not None and first.kind == "applied"
    good_digest = watcher.last_good.digest if watcher.last_good else None

    profile.write_text("not: [valid", encoding="utf-8")
    event = await watcher.poll_once()

    assert event is not None and event.kind == "rejected"
    assert event.digest == good_digest
    assert watcher.last_good is not None
    assert watcher.last_good.digest == good_digest
    assert rejected


@pytest.mark.unit
async def test_missing_patch_file_is_a_rejection(tmp_path: Path) -> None:
    watcher, _, overlay = _watcher(tmp_path)
    assert await watcher.poll_once() is None

    overlay.unlink()
    event = await watcher.poll_once()

    assert event is not None and event.kind == "rejected"
    assert watcher.last_good is not None


@pytest.mark.unit
async def test_async_callbacks_are_awaited(tmp_path: Path) -> None:
    calls: list[int] = []

    async def on_applied(envelope, snapshot) -> None:
        await asyncio.sleep(0)
        calls.append(envelope.version)

    watcher, _, overlay = _watcher(tmp_path, on_applied=on_applied)
    assert await watcher.poll_once() is None  # baseline
    _write(overlay, {"patches": [{"target": "sisyphus-runtime", "enabled": False}]})
    await watcher.poll_once()

    assert calls == [1]


@pytest.mark.unit
async def test_start_stop_loop_smoke(tmp_path: Path) -> None:
    applied: list[int] = []
    watcher, _, overlay = _watcher(
        tmp_path,
        on_applied=lambda envelope, snapshot: applied.append(envelope.version),
        interval_seconds=0.02,
    )
    await watcher.start()
    try:
        await asyncio.sleep(0.05)
        _write(overlay, {"patches": [{"target": "sisyphus-runtime", "remove": True}]})
        for _ in range(50):
            if applied:
                break
            await asyncio.sleep(0.02)
        assert applied == [1]
    finally:
        await watcher.stop()

    assert watcher._task is None
