import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);

function readText(relativePath) {
  return readFileSync(new URL(relativePath, contractRoot), "utf8");
}

function readJson(relativePath) {
  return JSON.parse(readText(relativePath));
}

test("capability definition registry is ordered, complete, and keeps fragments bounded", () => {
  const registry = readJson("parity-capability-fragments.v2.json");

  assert.equal(Array.isArray(registry.fragments), true);
  assert.equal(registry.fragments.length > 1, true);
  assert.equal(new Set(registry.fragments).size, registry.fragments.length);
  assert.deepEqual(
    readdirSync(contractRoot)
      .filter((fileName) =>
        /^parity-capability-definitions\.\d{2}-[a-z0-9-]+\.v2\.json$/u.test(
          fileName,
        ),
      )
      .sort(),
    [...registry.fragments].sort(),
  );

  const capabilityIds = [];
  for (const fileName of registry.fragments) {
    assert.match(
      fileName,
      /^parity-capability-definitions\.\d{2}-[a-z0-9-]+\.v2\.json$/u,
    );
    const source = readText(fileName);
    assert.equal(
      source.trimEnd().split("\n").length <= 800,
      true,
      `${fileName} exceeds the repository line limit`,
    );
    const fragment = JSON.parse(source);
    capabilityIds.push(
      ...fragment.capabilities.map((capability) => capability.id),
    );
  }

  assert.equal(new Set(capabilityIds).size, capabilityIds.length);
  assert.deepEqual(
    readJson("parity-manifest.v2.json").capabilities.map(
      (capability) => capability.id,
    ),
    capabilityIds,
  );
});
