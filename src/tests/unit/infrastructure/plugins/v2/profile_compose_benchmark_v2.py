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
    # Three short batches. A single host stall can inflate one p95; the gate
    # uses the median batch so the steady compose cost still has to stay under budget.
    batches: list[list[float]] = []
    snapshot = None
    for _ in range(3):
        for _ in range(5):
            snapshot = compose_profile_v2(profile, manifests, generation=1)
        samples: list[float] = []
        for _ in range(40):
            started = time.perf_counter()
            snapshot = compose_profile_v2(profile, manifests, generation=1)
            samples.append((time.perf_counter() - started) * 1000.0)
        batches.append(samples)

    # Check real output outside the timing interval, including external digest validation.
    assert snapshot is not None
    assert snapshot.profile_id == profile.profile_id
    assert snapshot.generation == 1
    assert snapshot.manifests == (manifest,)
    assert snapshot.entries
    assert parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot)) == snapshot
    print(
        json.dumps(
            {
                "batches_ms": batches,
                "samples_ms": batches[0],
                "gc_enabled": gc.isenabled(),
                "warmup": 5,
            }
        )
    )


if __name__ == "__main__":
    main()
