import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const runtime = require("@agistack/plugin-runtime");
const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../../shared/fixtures/marketplace-python-wasm-distribution.v2.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

async function refresh(payload) {
  const { digest: _, ...body } = payload.snapshot;
  payload.snapshot.digest = await runtime.digestV2(body);
  payload.descriptor.digest = payload.snapshot.digest;
  payload.envelope.snapshot_digest = payload.snapshot.digest;
  return runtime.parseControlPlaneDistributionV2(payload);
}

test("real signed Python package retains its manifest while renderer acknowledges an empty projection", async () => {
  const distribution = await runtime.parseControlPlaneDistributionV2(fixture);
  assert.equal(distribution.snapshot.manifests.length, 1);
  assert.equal(distribution.snapshot.entries.length, 1);
  assert.deepEqual(distribution.snapshot.manifests[0].modules[0].targets, [
    "python",
  ]);
  const reconciler = new runtime.PluginSnapshotReconcilerV2(
    new runtime.LoaderV2([], "desktop-renderer"),
  );
  try {
    const receipt = await reconciler.apply(distribution);
    assert.equal(receipt.status, "ack");
    assert.equal(receipt.applied_digest, distribution.snapshot.digest);
    assert.equal(receipt.applied_version, distribution.envelope.version);
    assert.equal(
      runtime.projectSnapshotEntriesV2(
        distribution.snapshot,
        "desktop-renderer",
      ).length,
      0,
    );
  } finally {
    await reconciler.close();
  }
});

test("declaring the external module executable on renderer is rejected by the real generated catalog", async () => {
  const changed = structuredClone(fixture);
  changed.snapshot.manifests[0].modules[0].targets = ["desktop-renderer"];
  const distribution = await refresh(changed);
  await assert.rejects(
    () =>
      new runtime.LoaderV2([], "desktop-renderer").stage(distribution.snapshot),
    (error) => error.code === "missing_target_catalog",
  );
  const reconciler = new runtime.PluginSnapshotReconcilerV2(
    new runtime.LoaderV2([], "desktop-renderer"),
  );
  try {
    const receipt = await reconciler.apply(distribution);
    assert.equal(receipt.status, "nack");
    assert.equal(receipt.error_code, "generation_apply_failed");
  } finally {
    await reconciler.close();
  }
});

test("ignored Python modules remain subject to snapshot schema and digest validation", async () => {
  const changed = structuredClone(fixture);
  changed.snapshot.manifests[0].modules[0].artifact.digest = "0".repeat(64);
  await assert.rejects(() => runtime.parseControlPlaneDistributionV2(changed));
  changed.snapshot.manifests[0].modules[0].targets = ["unregistered-plane"];
  await assert.rejects(() => refresh(changed));
});
