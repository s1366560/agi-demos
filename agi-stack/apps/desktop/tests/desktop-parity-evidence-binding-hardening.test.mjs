import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { validateEvidenceRun } from "../contracts/desktop-web-parity/evidence-run-validator.mjs";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const pinnedRevision = "1111111111111111111111111111111111111111";
const desiredContractRepositoryPath =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";

function readContractJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

function createRun(capabilityId) {
  const run = readContractJson("evidence-run.v1.template.json");
  run.record_kind = "run";
  run.desired_contract = {
    path: desiredContractRepositoryPath,
    path_base: "repository_root",
    artifact_id: "contract-report",
    schema_version: "2.0.0",
    revision: pinnedRevision,
    sha256: "a".repeat(64),
  };
  for (const key of Object.keys(run.source_revisions)) {
    run.source_revisions[key] = pinnedRevision;
  }
  run.source_state = {
    head_revision: pinnedRevision,
    worktree_state: "clean",
  };
  run.capability_results[0].capability_id = capabilityId;
  run.capability_results[0].contract_reference =
    `${desiredContractRepositoryPath}#${capabilityId}`;
  run.artifacts = [
    {
      artifact_id: "contract-report",
      kind: "report",
      channel: "shared",
      evidence_roles: ["contract"],
      location: "contract-report.json",
      sha256: "b".repeat(64),
      produced_at: run.completed_at,
    },
  ];
  return run;
}

function createManifest(...capabilityIds) {
  return {
    schema_version: "2.0.0",
    references: {
      audit_revision: pinnedRevision,
      web_revision: pinnedRevision,
      desktop_revision: pinnedRevision,
    },
    capabilities: capabilityIds.map((id) => ({ id })),
  };
}

test("full-manifest runs cover the manifest capability identity set exactly", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const manifest = createManifest("full-manifest-a", "full-manifest-b");
  const run = createRun("full-manifest-a");
  run.run_scope = "full_manifest";

  const missingErrors = validateEvidenceRun(schema, run, { manifest });
  assert.equal(
    missingErrors.some(
      (error) =>
        error.includes("$.capability_results") &&
        error.includes("full_manifest") &&
        error.includes("missing capability_id full-manifest-b"),
    ),
    true,
  );

  const secondResult = structuredClone(run.capability_results[0]);
  secondResult.capability_id = "full-manifest-b";
  secondResult.contract_reference =
    `${desiredContractRepositoryPath}#full-manifest-b`;
  run.capability_results.push(secondResult);
  assert.equal(
    validateEvidenceRun(schema, run, { manifest }).some(
      (error) =>
        error.includes("$.capability_results") &&
        error.includes("full_manifest"),
    ),
    false,
  );

  run.capability_results[1].capability_id = "full-manifest-extra";
  run.capability_results[1].contract_reference =
    `${desiredContractRepositoryPath}#full-manifest-extra`;
  assert.equal(
    validateEvidenceRun(schema, run, { manifest }).some(
      (error) =>
        error.includes("$.capability_results") &&
        error.includes("full_manifest") &&
        error.includes("unexpected capability_id full-manifest-extra"),
    ),
    true,
  );
});

test("capability-slice runs may retain a strict subset of manifest capabilities", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const run = createRun("slice-a");
  const manifest = createManifest("slice-a", "slice-b");

  assert.equal(run.run_scope, "capability_slice");
  assert.equal(
    validateEvidenceRun(schema, run, { manifest }).some((error) =>
      error.includes("full_manifest"),
    ),
    false,
  );
});

test("run revisions may advance beyond the manifest audit baseline", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const run = createRun("revision-binding");
  const manifest = createManifest("revision-binding");
  manifest.references = {
    audit_revision: "2".repeat(40),
    web_revision: "2".repeat(40),
    desktop_revision: "2".repeat(40),
  };

  const errors = validateEvidenceRun(schema, run, { manifest });
  assert.equal(
    errors.some((error) => error.includes("manifest references.")),
    false,
  );
});

test("desired contract path is bound to the inspected repository-relative path", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const run = createRun("repository-path-binding");
  const fabricatedPath =
    "agi-stack/apps/desktop/contracts/desktop-web-parity/fabricated-manifest.json";
  run.desired_contract.path = fabricatedPath;
  run.capability_results[0].contract_reference =
    `${fabricatedPath}#repository-path-binding`;

  const errors = validateEvidenceRun(schema, run, {
    manifest: createManifest("repository-path-binding"),
    repositoryBinding: {
      headRevision: pinnedRevision,
      worktreeState: "clean",
      contractExistsAtHead: true,
      contractSha256: run.desired_contract.sha256,
      workingTreeContractSha256: run.desired_contract.sha256,
      contractMatchesWorkingTree: true,
      contractRelativePath: desiredContractRepositoryPath,
    },
  });
  assert.equal(
    errors.some(
      (error) =>
        error.includes("$.desired_contract.path") &&
        error.includes("repository binding"),
    ),
    true,
  );
});
