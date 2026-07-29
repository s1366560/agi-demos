import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  computeEvidenceDigest,
  validateEvidenceRun,
} from "../contracts/desktop-web-parity/evidence-run-validator.mjs";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const pinnedRevision = "1111111111111111111111111111111111111111";
const desiredContractRepositoryPath =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";
const schemaBody = readFileSync(
  new URL("evidence-run.v1.schema.json", contractRoot),
);
const desiredContractBody = Buffer.from(
  `${JSON.stringify(
    {
      schema_version: "2.0.0",
      capabilities: [{ id: "artifact-authenticity" }],
    },
    null,
    2,
  )}\n`,
);

function readContractJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

function createVerifiableRun(body = Buffer.from("verified artifact bytes\n")) {
  const run = readContractJson("evidence-run.v1.template.json");
  const capabilityId = "artifact-authenticity";
  const contractReference =
    `${desiredContractRepositoryPath}#${capabilityId}`;
  const desiredContractSha256 = createHash("sha256")
    .update(desiredContractBody)
    .digest("hex");
  run.record_kind = "run";
  run.artifact_location_base = "evidence_run_directory";
  run.schema_artifact_id = "evidence-schema";
  run.desired_contract = {
    path: desiredContractRepositoryPath,
    path_base: "repository_root",
    artifact_id: "desired-contract",
    schema_version: "2.0.0",
    revision: pinnedRevision,
    sha256: desiredContractSha256,
  };
  for (const key of Object.keys(run.source_revisions)) {
    run.source_revisions[key] = pinnedRevision;
  }
  run.source_state = {
    head_revision: pinnedRevision,
    worktree_state: "clean",
  };
  run.started_at = "2026-07-29T08:00:00Z";
  run.completed_at = "2026-07-29T08:01:00Z";
  run.capability_results[0] = {
    capability_id: capabilityId,
    contract_reference: contractReference,
    result: "not_run",
    summary:
      "Artifact authenticity is verified independently of capability execution.",
    evidence: {
      build: "not_run",
      browser: "not_run",
      native: "not_run",
    },
    artifact_ids: ["evidence-schema", "desired-contract"],
    parity_judgment: {
      disposition: "accepted",
      statement: "The retained artifact contract was reviewed.",
      judgment_audit: {
        agent_id: "parity-review-agent",
        tool_name: "record_parity_judgment",
        input: {
          contract_reference: contractReference,
          observation_summary: "The artifact evidence was reviewed.",
        },
        output: {
          verdict: "accepted",
          summary: "The artifact evidence is authentic.",
        },
        rationale: "The artifact bytes and metadata are bound by SHA-256.",
        latency_ms: 42,
        recorded_at: "2026-07-29T08:00:00Z",
      },
    },
    intentional_deviation: {
      disposition: "none",
      statement: null,
      judgment_audit: null,
    },
  };
  run.artifacts = [
    {
      artifact_id: "shared-contract-report",
      kind: "report",
      channel: "shared",
      evidence_roles: ["contract"],
      location: "contract-report.json",
      sha256: createHash("sha256").update(body).digest("hex"),
      produced_at: "2026-07-29T08:00:30Z",
    },
    {
      artifact_id: "evidence-schema",
      kind: "report",
      channel: "shared",
      evidence_roles: ["contract"],
      location: "evidence-run.v1.schema.json",
      sha256: createHash("sha256").update(schemaBody).digest("hex"),
      produced_at: "2026-07-29T08:00:30Z",
    },
    {
      artifact_id: "desired-contract",
      kind: "report",
      channel: "shared",
      evidence_roles: ["contract"],
      location: "parity-manifest.v2.json",
      sha256: desiredContractSha256,
      produced_at: "2026-07-29T08:00:30Z",
    },
  ];
  run.capability_results[0].parity_judgment.judgment_audit.input.evidence_digest =
    computeEvidenceDigest(run, run.capability_results[0]);
  return run;
}

function repositoryBindingFor(run) {
  return {
    headRevision: run.source_revisions.repository_revision,
    worktreeState: "clean",
    contractExistsAtHead: true,
    contractSha256: run.desired_contract.sha256,
    workingTreeContractSha256: run.desired_contract.sha256,
    contractMatchesWorkingTree: true,
    contractRelativePath: desiredContractRepositoryPath,
  };
}

function createTemporaryDirectory(t, prefix) {
  const directory = mkdtempSync(join(tmpdir(), prefix));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return directory;
}

function writeVerifiableArtifacts(evidenceRoot, run, reportBody) {
  const bodies = new Map([
    ["contract-report.json", reportBody],
    ["evidence-run.v1.schema.json", schemaBody],
    ["parity-manifest.v2.json", desiredContractBody],
  ]);
  for (const artifact of run.artifacts) {
    writeFileSync(join(evidenceRoot, artifact.location), bodies.get(artifact.location));
  }
}

test("run artifacts require a live evidence root and matching regular file bytes", (t) => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const body = Buffer.from("verified artifact bytes\n");
  const run = createVerifiableRun(body);
  const evidenceRoot = createTemporaryDirectory(t, "desktop-parity-evidence-");
  writeVerifiableArtifacts(evidenceRoot, run, body);
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  const repositoryBinding = repositoryBindingFor(run);

  assert.deepEqual(
    validateEvidenceRun(schema, run, { evidenceRunPath, repositoryBinding }),
    [],
  );
  assert.equal(
    validateEvidenceRun(schema, run, { repositoryBinding }).some((error) =>
      error.includes("evidenceRunPath"),
    ),
    true,
  );

  const mismatched = structuredClone(run);
  mismatched.artifacts[0].sha256 = "f".repeat(64);
  assert.equal(
    validateEvidenceRun(schema, mismatched, {
      evidenceRunPath,
      repositoryBinding,
    }).some(
      (error) => error.includes("sha256") && error.includes("artifact bytes"),
    ),
    true,
  );
});

test("run artifact locations reject absolute paths and traversal", (t) => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const run = createVerifiableRun();
  const evidenceRoot = createTemporaryDirectory(t, "desktop-parity-evidence-");
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  const repositoryBinding = repositoryBindingFor(run);

  const absolute = structuredClone(run);
  absolute.artifacts[0].location = join(evidenceRoot, "contract-report.json");
  assert.equal(
    validateEvidenceRun(schema, absolute, {
      evidenceRunPath,
      repositoryBinding,
    }).some(
      (error) => error.includes("location") && error.includes("absolute"),
    ),
    true,
  );

  const traversal = structuredClone(run);
  traversal.artifacts[0].location = "../contract-report.json";
  assert.equal(
    validateEvidenceRun(schema, traversal, {
      evidenceRunPath,
      repositoryBinding,
    }).some(
      (error) => error.includes("location") && error.includes("traversal"),
    ),
    true,
  );
});

test("run artifact locations reject symlink escapes and non-files", (t) => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const body = Buffer.from("external artifact bytes\n");
  const run = createVerifiableRun(body);
  const evidenceRoot = createTemporaryDirectory(t, "desktop-parity-evidence-");
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  const externalRoot = createTemporaryDirectory(t, "desktop-parity-external-");
  const repositoryBinding = repositoryBindingFor(run);
  writeFileSync(join(externalRoot, "contract-report.json"), body);
  symlinkSync(externalRoot, join(evidenceRoot, "escaped"), "dir");

  const escaped = structuredClone(run);
  escaped.artifacts[0].location = "escaped/contract-report.json";
  assert.equal(
    validateEvidenceRun(schema, escaped, {
      evidenceRunPath,
      repositoryBinding,
    }).some((error) => error.includes("location") && error.includes("symlink")),
    true,
  );

  mkdirSync(join(evidenceRoot, "directory-artifact"));
  const directory = structuredClone(run);
  directory.artifacts[0].location = "directory-artifact";
  assert.equal(
    validateEvidenceRun(schema, directory, {
      evidenceRunPath,
      repositoryBinding,
    }).some((error) => error.includes("regular file")),
    true,
  );
});

test("run artifact timestamps must fall within the run time window", (t) => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const body = Buffer.from("verified artifact bytes\n");
  const run = createVerifiableRun(body);
  const evidenceRoot = createTemporaryDirectory(t, "desktop-parity-evidence-");
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  const repositoryBinding = repositoryBindingFor(run);
  writeVerifiableArtifacts(evidenceRoot, run, body);

  for (const producedAt of ["2026-07-29T07:59:59Z", "2026-07-29T08:01:01Z"]) {
    const outsideWindow = structuredClone(run);
    outsideWindow.artifacts[0].produced_at = producedAt;
    assert.equal(
      validateEvidenceRun(schema, outsideWindow, {
        evidenceRunPath,
        repositoryBinding,
      }).some(
        (error) =>
          error.includes("produced_at") && error.includes("run time window"),
      ),
      true,
      producedAt,
    );
  }
});

test("run-local schema and desired contract references must resolve and stay hash-bound", (t) => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const body = Buffer.from("verified artifact bytes\n");
  const run = createVerifiableRun(body);
  const evidenceRoot = createTemporaryDirectory(t, "desktop-parity-evidence-");
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  const repositoryBinding = repositoryBindingFor(run);
  writeFileSync(join(evidenceRoot, "contract-report.json"), body);

  const missingErrors = validateEvidenceRun(schema, run, {
    evidenceRunPath,
    repositoryBinding,
  });
  assert.equal(
    missingErrors.some(
      (error) =>
        error.includes("schema_artifact_id") && error.includes("missing"),
    ),
    true,
  );
  assert.equal(
    missingErrors.some(
      (error) =>
        error.includes("desired_contract.artifact_id") &&
        error.includes("missing"),
    ),
    true,
  );

  writeFileSync(join(evidenceRoot, "evidence-run.v1.schema.json"), schemaBody);
  writeFileSync(join(evidenceRoot, "parity-manifest.v2.json"), desiredContractBody);
  assert.deepEqual(
    validateEvidenceRun(schema, run, { evidenceRunPath, repositoryBinding }),
    [],
  );

  writeFileSync(
    join(evidenceRoot, "parity-manifest.v2.json"),
    Buffer.from("tampered contract\n"),
  );
  assert.equal(
    validateEvidenceRun(schema, run, {
      evidenceRunPath,
      repositoryBinding,
    }).some(
      (error) =>
        error.includes("desired_contract.artifact_id") &&
        error.includes("sha256"),
    ),
    true,
  );
});
