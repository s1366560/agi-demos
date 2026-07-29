import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const repositoryRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const generatorPath = fileURLToPath(
  new URL("generate-parity-manifest-v2.mjs", contractRoot),
);
const pluginHubEntry = "web/src/pages/tenant/PluginHub.tsx";
const reviewedPluginHubRedirect = {
  source_entry: pluginHubEntry,
  source_owner_capability_id: "tenant-tenant-plugins",
  route_registration_id:
    "production-route-path-tenant-tenantid-project-projectid-channels",
  relationship: "canonical_redirect_target",
};

test("generator binds a reviewed redirect target and its audited source hash", (t) => {
  const outputRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-reviewed-web-entry-"),
  );
  const outputPath = join(outputRoot, "review-inputs.jsonl");
  t.after(() => rmSync(outputRoot, { recursive: true, force: true }));

  const result = spawnSync(
    process.execPath,
    [generatorPath, "--emit-inputs", outputPath],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
    },
  );
  assert.equal(result.status, 0, `${result.stderr}\n${result.stdout}`);

  const records = readFileSync(outputPath, "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const channels = records.find(
    (record) =>
      record.input.capability_id === "project-project-channels",
  );
  assert.ok(channels);
  assert.deepEqual(
    channels.input.reviewed_additional_web_entries,
    [reviewedPluginHubRedirect],
  );
  assert.ok(channels.input.routed_source_entries.includes(pluginHubEntry));

  const inventory = JSON.parse(
    readFileSync(new URL("web-route-inventory.v2.json", contractRoot), "utf8"),
  );
  const auditedPluginHub = inventory.audited_sources.find(
    (source) => source.source_entry === pluginHubEntry,
  );
  assert.ok(auditedPluginHub);
  assert.deepEqual(
    channels.input.audited_web_sources.find(
      (source) => source.source_entry === pluginHubEntry,
    ),
    auditedPluginHub,
  );
});
