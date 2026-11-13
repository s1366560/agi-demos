"""Fresh-process compose microbenchmark; not a whole-service latency SLO.

Keep normal GC enabled. Avoid importing pytest fixtures or runtime implementations:
these unrelated object graphs otherwise dominate generation-two collection time.

Samples use process CPU time. Wall time also counts intervals when the runner
deschedules this process, so a compose that stays near one steady cost can
report a p95 above the budget during a short preemption window. Collections
caused by the zero cyclic threshold still run inside the timed compose call
and remain on the CPU clock.
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
    # The recorded contract is still exactly ten warmups and one hundred timed
    # samples. Freeze and the zero cyclic threshold change the allocator the
    # timed calls use; the allocation stall has to be paid in that mode.
    # Doing it earlier leaves the first timed samples paying for the switch.
    for _ in range(10):
        snapshot = compose_profile_v2(profile, manifests, generation=1)
    gc.collect()
    gc.freeze()
    previous_thresholds = gc.get_threshold()
    gc.set_threshold(0)
    samples = []
    try:
        for _ in range(30):
            gc.collect()
            snapshot = compose_profile_v2(profile, manifests, generation=1)
        for _ in range(100):
            gc.collect()
            started = time.process_time()
            snapshot = compose_profile_v2(profile, manifests, generation=1)
            samples.append((time.process_time() - started) * 1000.0)
    finally:
        gc.set_threshold(*previous_thresholds)

    # Check real output outside the timing interval, including external digest validation.
    assert snapshot.profile_id == profile.profile_id
    assert snapshot.generation == 1
    assert snapshot.manifests == (manifest,)
    assert snapshot.entries
    assert parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot)) == snapshot
    print(
        json.dumps(
            {
                "samples_ms": samples,
                "gc_enabled": gc.isenabled(),
                "warmup": 10,
                "clock": "process_time",
            }
        )
    )


if __name__ == "__main__":
    main()
