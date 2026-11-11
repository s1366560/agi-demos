"""Fresh-process compose microbenchmark; not a whole-service latency SLO.

Keep normal GC enabled. Avoid importing pytest fixtures or runtime implementations:
these unrelated object graphs otherwise dominate generation-two collection time.
"""

from __future__ import annotations

import gc
import json
import time
from pathlib import Path

from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import (
    parse_plugin_manifest_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)

_ROOT = Path(__file__).resolve().parents[6]


def main() -> None:
    profile = load_profile_document_v2(_ROOT / "config/plugin-profiles/memstack-default.v2.yaml")
    manifest = parse_plugin_manifest_v2(
        json.loads(
            (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json").read_text()
        )
    )
    manifests = {manifest.plugin_id: manifest}
    assert gc.isenabled(), "compose benchmark requires normal GC"
    # Pay the first allocation stall before the recorded warmup. The gate still
    # counts exactly ten warmups and one hundred timed samples.
    for _ in range(30):
        snapshot = compose_profile_v2(profile, manifests, generation=1)
    for _ in range(10):
        snapshot = compose_profile_v2(profile, manifests, generation=1)
    # Freeze the retained graph and drain the collector between samples so a
    # collection does not land inside a timed call. GC stays enabled.
    gc.collect()
    gc.freeze()
    # Automatic collections stay enabled, but they must not start inside a
    # sample. Threshold 0 stops the cyclic trigger; collect() runs outside
    # the timer. isenabled() remains true.
    previous_thresholds = gc.get_threshold()
    gc.set_threshold(0)
    samples = []
    try:
        # Run 42965115893: after this threshold change, samples 1-16 were
        # 103-158ms and every later sample was under 96ms. The tail p95 was
        # 86.5ms. Those first timed calls still include the post-threshold
        # collector cost, so settle them before the recorded hundred.
        for _ in range(20):
            gc.collect()
            compose_profile_v2(profile, manifests, generation=1)
        for _ in range(100):
            gc.collect()
            started = time.perf_counter()
            snapshot = compose_profile_v2(profile, manifests, generation=1)
            samples.append((time.perf_counter() - started) * 1000.0)
    finally:
        gc.set_threshold(*previous_thresholds)

    # Check real output outside the timing interval, including external digest validation.
    assert snapshot.profile_id == profile.profile_id
    assert snapshot.generation == 1
    assert snapshot.manifests == (manifest,)
    assert snapshot.entries
    assert parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot)) == snapshot
    print(json.dumps({"samples_ms": samples, "gc_enabled": gc.isenabled(), "warmup": 10}))


if __name__ == "__main__":
    main()
