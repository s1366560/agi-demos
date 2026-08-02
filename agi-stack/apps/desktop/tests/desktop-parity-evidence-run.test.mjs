import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";
import {
  computeEvidenceDigest,
  inspectEvidenceRepositoryBinding,
  validateEvidenceRun,
} from "../contracts/desktop-web-parity/evidence-run-validator.mjs";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const qaLog = readFileSync(new URL("../QA.md", import.meta.url), "utf8");
const pinnedRevision = "1111111111111111111111111111111111111111";
const desiredContractRepositoryPath =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";

function readContractJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

test("repository binding reads the committed contract from the requested HEAD", () => {
  const repositoryRoot = fileURLToPath(
    new URL("../../../../", import.meta.url),
  );
  const binding = inspectEvidenceRepositoryBinding({
    repositoryRoot,
    contractRelativePath: "AGENTS.md",
  });
  assert.match(binding.headRevision, /^[0-9a-f]{40}$/u);
  assert.equal(binding.contractExistsAtHead, true);
  assert.match(binding.contractSha256, /^[0-9a-f]{64}$/u);
  assert.equal(binding.workingTreeContractSha256, binding.contractSha256);
  assert.equal(binding.contractMatchesWorkingTree, true);
  assert.equal(binding.contractRelativePath, "AGENTS.md");
});

test("repository binding reads committed contracts larger than the default exec buffer", () => {
  const repositoryRoot = fileURLToPath(
    new URL("../../../../", import.meta.url),
  );
  const binding = inspectEvidenceRepositoryBinding({
    repositoryRoot,
    contractRelativePath: desiredContractRepositoryPath,
  });
  assert.equal(binding.contractExistsAtHead, true);
  assert.match(binding.contractSha256, /^[0-9a-f]{64}$/u);
  assert.equal(binding.workingTreeContractSha256, binding.contractSha256);
  assert.equal(binding.contractMatchesWorkingTree, true);
});

function createAcceptedRun(capabilityId) {
  const run = readContractJson("evidence-run.v1.template.json");
  const contractReference =
    `${desiredContractRepositoryPath}#${capabilityId}`;
  run.record_kind = "run";
  run.artifact_location_base = "evidence_run_directory";
  run.schema_artifact_id = "shared-contract-report";
  run.desired_contract = {
    path: desiredContractRepositoryPath,
    path_base: "repository_root",
    artifact_id: "shared-contract-report",
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
  run.capability_results[0] = {
    capability_id: capabilityId,
    contract_reference: contractReference,
    result: "passed",
    summary: "The capability passed every required evidence channel.",
    evidence: {
      build: "not_run",
      browser: "not_run",
      native: "not_run",
    },
    artifact_ids: [],
    parity_judgment: {
      disposition: "accepted",
      statement:
        "The retained evidence satisfies the desired capability contract.",
      judgment_audit: {
        agent_id: "parity-review-agent",
        tool_name: "record_parity_judgment",
        input: {
          contract_reference: contractReference,
          observation_summary: "The capability evidence was reviewed.",
        },
        output: {
          verdict: "accepted",
          summary: "The capability is equivalent for the reviewed state.",
        },
        rationale: "The evidence covers every required channel and state.",
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
      sha256: "b".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
  ];
  run.capability_results[0].parity_judgment.judgment_audit.input.evidence_digest =
    computeEvidenceDigest(run, run.capability_results[0]);
  return run;
}

test("standalone evidence-run template validates without becoming the desired parity manifest", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const template = readContractJson("evidence-run.v1.template.json");
  assert.deepEqual(validateJsonSchema(schema, template), []);
  assert.equal(schema.title, "MemStack Desktop Parity Evidence Run");
  assert.equal(template.$schema, "./evidence-run.v1.schema.json");
  assert.equal(template.artifact_location_base, "evidence_run_directory");
  assert.equal(typeof template.schema_artifact_id, "string");
  assert.equal(template.desired_contract.path_base, "repository_root");
  assert.equal(typeof template.desired_contract.artifact_id, "string");
  assert.equal(template.run_scope, "capability_slice");
  assert.equal(Object.hasOwn(template, "cases"), false);
  assert.equal(Object.hasOwn(template, "target_disposition"), false);
});

test("QA log binds the completion audit to its real historical revision", () => {
  assert.match(qaLog, /main@7503434b475312e7068987617dd0ed484054e21a/u);
  assert.match(
    qaLog,
    /results in this section are bound\s+to that audit commit/u,
  );
  assert.doesNotMatch(qaLog, /7503434b42bf6e62c110ba9603466c66985fb625/u);
  assert.doesNotMatch(qaLog, /passed at the current HEAD/u);
  assert.doesNotMatch(qaLog, /current validation ran from/u);
});

test("evidence-run schema requires reproducible run identity, revisions, state and evidence", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const template = readContractJson("evidence-run.v1.template.json");
  const malformed = structuredClone(template);
  delete malformed.run_id;
  delete malformed.run_scope;
  delete malformed.artifact_location_base;
  delete malformed.schema_artifact_id;
  delete malformed.desired_contract.path_base;
  delete malformed.desired_contract.artifact_id;
  malformed.source_revisions.desktop_revision = "not-a-commit";
  delete malformed.matched_state.interaction_state;
  delete malformed.matched_state.permission_state;
  delete malformed.capability_results[0].evidence.native;
  delete malformed.artifacts;
  const validation = validateJsonSchema(schema, malformed);
  assert.equal(
    validation.some((error) => error.includes("run_id is required")),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("run_scope is required")),
    true,
  );
  assert.equal(
    validation.some((error) =>
      error.includes("artifact_location_base is required"),
    ),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("schema_artifact_id is required")),
    true,
  );
  assert.equal(
    validation.some((error) =>
      error.includes("desired_contract.path_base is required"),
    ),
    true,
  );
  assert.equal(
    validation.some((error) =>
      error.includes("desired_contract.artifact_id is required"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("desktop_revision") && error.includes("must match"),
    ),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("interaction_state is required")),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("permission_state is required")),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("native is required")),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("artifacts is required")),
    true,
  );
});

test("reviewed intentional deviations require a structured judgment audit", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const template = readContractJson("evidence-run.v1.template.json");
  const reviewed = structuredClone(template);
  reviewed.capability_results[0].intentional_deviation = {
    disposition: "accepted",
    statement: "The native sidecar replaces the cloud sandbox authority.",
    judgment_audit: {
      agent_id: "parity-review-agent",
      tool_name: "record_parity_judgment",
      input: {
        contract_reference: "sandbox-runtime-fail-closed",
        evidence_digest: `sha256:${"a".repeat(64)}`,
        observation_summary: "Desktop uses a native workspace boundary.",
      },
      output: {
        verdict: "accepted",
        summary:
          "The deviation preserves the required native security boundary.",
      },
      rationale:
        "The observable result remains equivalent without claiming cloud isolation.",
      latency_ms: 42,
      recorded_at: "2026-07-29T08:00:00Z",
    },
  };
  assert.deepEqual(validateJsonSchema(schema, reviewed), []);
  delete reviewed.capability_results[0].intentional_deviation.judgment_audit
    .latency_ms;
  const validation = validateJsonSchema(schema, reviewed);
  assert.equal(
    validation.some((error) => error.includes("latency_ms is required")),
    true,
  );
});

test("visual parity stays pending until a structured Agent judgment is attached", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const pending = readContractJson("evidence-run.v1.template.json");
  assert.deepEqual(validateJsonSchema(schema, pending), []);
  assert.equal(
    pending.capability_results[0].parity_judgment.disposition,
    "pending_review",
  );
  assert.equal(
    pending.capability_results[0].parity_judgment.judgment_audit,
    null,
  );
  const invalidAccepted = structuredClone(pending);
  invalidAccepted.capability_results[0].parity_judgment.disposition =
    "accepted";
  assert.equal(
    validateJsonSchema(schema, invalidAccepted).some((error) =>
      error.includes("must satisfy exactly one oneOf branch"),
    ),
    true,
  );
});

test("evidence-run schema rejects unsupported results and undeclared fields", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const malformed = readContractJson("evidence-run.v1.template.json");
  malformed.capability_results[0].result = "claimed";
  malformed.untracked_claim = true;
  const validation = validateJsonSchema(schema, malformed);
  assert.equal(
    validation.some(
      (error) => error.includes("result") && error.includes("must be one of"),
    ),
    true,
  );
  assert.equal(
    validation.some((error) =>
      error.includes("untracked_claim is not allowed"),
    ),
    true,
  );
});

test("run records cannot claim executed channels without timestamps and artifacts", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const malformed = readContractJson("evidence-run.v1.template.json");
  malformed.record_kind = "run";
  malformed.capability_results[0].result = "passed";
  malformed.capability_results[0].evidence = {
    build: "passed",
    browser: "passed",
    native: "passed",
  };
  malformed.evidence.build.status = "passed";
  malformed.evidence.browser.status = "passed";
  malformed.evidence.native.status = "passed";
  const validation = validateEvidenceRun(schema, malformed);
  assert.equal(
    validation.some(
      (error) => error.includes("artifacts") && error.includes("at least 1"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("started_at") && error.includes("received null"),
    ),
    true,
  );
});

test("run records reject dangling artifact references and placeholder revisions", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const malformed = readContractJson("evidence-run.v1.template.json");
  malformed.record_kind = "run";
  malformed.capability_results[0].artifact_ids = ["missing-artifact"];
  malformed.evidence.browser.artifact_ids = ["missing-artifact"];
  const validation = validateEvidenceRun(schema, malformed);
  assert.equal(
    validation.some(
      (error) =>
        error.includes("missing-artifact") && error.includes("unknown"),
    ),
    true,
  );
  assert.equal(
    validation.some((error) => error.includes("placeholder revision")),
    true,
  );
});

test("capability evidence cannot execute when the run channel was not run", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const malformed = readContractJson("evidence-run.v1.template.json");
  const revision = "1111111111111111111111111111111111111111";
  malformed.record_kind = "run";
  malformed.desired_contract.revision = revision;
  for (const key of Object.keys(malformed.source_revisions)) {
    malformed.source_revisions[key] = revision;
  }
  malformed.capability_results[0].evidence.browser = "passed";
  malformed.capability_results[0].artifact_ids = ["browser-screenshot"];
  malformed.artifacts = [
    {
      artifact_id: "browser-screenshot",
      kind: "screenshot",
      channel: "browser",
      evidence_roles: ["web_renderer"],
      location: "browser.png",
      sha256: "b".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
    {
      artifact_id: "unreferenced-shared-report",
      kind: "report",
      channel: "shared",
      evidence_roles: ["contract"],
      location: "report.json",
      sha256: "a".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
  ];
  const validation = validateEvidenceRun(schema, malformed);
  assert.equal(
    validation.some(
      (error) =>
        error.includes("capability_results[0].evidence.browser") &&
      error.includes("run channel is not_run"),
    ),
    true,
  );

  malformed.evidence.browser = {
    status: "failed",
    command: "make -C agi-stack desktop-browser-qa",
    started_at: "2026-07-29T08:00:00Z",
    completed_at: "2026-07-29T08:01:00Z",
    summary: "The Browser evidence run failed.",
    artifact_ids: ["browser-screenshot"],
  };
  const failedRunValidation = validateEvidenceRun(schema, malformed);
  assert.equal(
    failedRunValidation.some(
      (error) =>
        error.includes("capability_results[0].evidence.browser") &&
        error.includes("cannot be passed") &&
        error.includes("run channel is failed"),
    ),
    true,
  );
});

test("executed capability channels require a referenced artifact from that channel", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const malformed = readContractJson("evidence-run.v1.template.json");
  const revision = "1111111111111111111111111111111111111111";
  malformed.record_kind = "run";
  malformed.desired_contract.revision = revision;
  for (const key of Object.keys(malformed.source_revisions)) {
    malformed.source_revisions[key] = revision;
  }
  malformed.capability_results[0].evidence.browser = "passed";
  malformed.capability_results[0].artifact_ids = ["shared-report"];
  malformed.artifacts = [
    {
      artifact_id: "browser-screenshot",
      kind: "screenshot",
      channel: "browser",
      evidence_roles: ["web_renderer"],
      location: "browser.png",
      sha256: "a".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
    {
      artifact_id: "shared-report",
      kind: "report",
      channel: "shared",
      evidence_roles: ["web_renderer"],
      location: "report.json",
      sha256: "b".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
  ];
  malformed.evidence.browser = {
    status: "passed",
    command: "make -C agi-stack desktop-browser-qa",
    started_at: "2026-07-29T08:00:00Z",
    completed_at: "2026-07-29T08:01:00Z",
    summary: "Browser evidence completed.",
    artifact_ids: ["browser-screenshot"],
  };
  const validation = validateEvidenceRun(schema, malformed);
  assert.equal(
    validation.some(
      (error) =>
        error.includes("capability_results[0].artifact_ids") &&
        error.includes("browser channel artifact"),
    ),
    true,
  );
});

test("a passed capability must pass every channel required by its manifest contract", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const manifest = readContractJson("parity-manifest.v2.json");
  const capability = manifest.capabilities.find(
    (candidate) => candidate.id === "agent-workspace-tenant-agent-workspace",
  );
  assert.ok(capability);
  const run = createAcceptedRun(capability.id);
  const validation = validateEvidenceRun(schema, run, { manifest });
  assert.equal(
    validation.some(
      (error) =>
        error.includes("capability_results[0].evidence.build") &&
        error.includes("required") &&
        error.includes("passed"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("capability_results[0].evidence.browser") &&
        error.includes("required") &&
        error.includes("passed"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("capability_results[0].evidence.native") &&
        error.includes("required") &&
        error.includes("passed"),
    ),
    true,
  );
});

test("passed capabilities require exact evidence roles for every surface requirement", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const capabilityId = "renderer-proof";
  const run = createAcceptedRun(capabilityId);
  run.capability_results[0].evidence.browser = "passed";
  run.capability_results[0].artifact_ids = ["web-renderer-screenshot"];
  run.artifacts = [
    {
      artifact_id: "web-renderer-screenshot",
      kind: "screenshot",
      channel: "browser",
      evidence_roles: ["web_renderer"],
      location: "web-renderer.png",
      sha256: "b".repeat(64),
      produced_at: "2026-07-29T08:00:00Z",
    },
  ];
  run.evidence.browser = {
    status: "passed",
    command: "corepack pnpm run qa:paired-production",
    started_at: "2026-07-29T08:00:00Z",
    completed_at: "2026-07-29T08:01:00Z",
    summary: "Only the Web renderer was captured.",
    artifact_ids: ["web-renderer-screenshot"],
  };
  const manifest = {
    schema_version: "2.0.0",
    capabilities: [
      {
        id: capabilityId,
        evidence_requirements: ["web_renderer", "desktop_renderer"],
        surfaces: {},
      },
    ],
  };
  const validation = validateEvidenceRun(schema, run, { manifest });
  assert.equal(
    validation.some(
      (error) =>
        error.includes("desktop_renderer") &&
        error.includes("browser artifact"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("web_renderer") && error.includes("browser artifact"),
    ),
    false,
  );

  const mismatchedRole = createAcceptedRun("role-channel-binding");
  mismatchedRole.capability_results[0].result = "not_run";
  mismatchedRole.artifacts[0].channel = "browser";
  mismatchedRole.artifacts[0].evidence_roles = ["sidecar_authority"];
  const mismatchedErrors = validateEvidenceRun(schema, mismatchedRole);
  assert.equal(
    mismatchedErrors.some((error) =>
      ["evidence_roles", "sidecar_authority", "browser"].every((part) =>
        error.includes(part),
      ),
    ),
    true,
  );
});

test("passed capabilities require accepted intentional-deviation judgment", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const capabilityId = "intentional-deviation-proof";
  const run = createAcceptedRun(capabilityId);
  const manifest = {
    schema_version: "2.0.0",
    capabilities: [
      {
        id: capabilityId,
        evidence_requirements: [],
        surfaces: {
          desktop_local: {
            intentional_deviation:
              "Local mode intentionally omits cloud billing.",
          },
        },
      },
    ],
  };
  const deviationErrors = () =>
    validateEvidenceRun(schema, run, { manifest }).filter((error) =>
      error.includes("intentional_deviation"),
    );

  assert.equal(
    deviationErrors().some((error) =>
      error.includes("intentional_deviation must be accepted"),
    ),
    true,
  );

  run.capability_results[0].intentional_deviation = {
    disposition: "rejected",
    statement: "The Local omission is an accepted product boundary.",
    judgment_audit: {
      agent_id: "parity-review-agent",
      tool_name: "record_intentional_deviation_judgment",
      input: {
        contract_reference: run.capability_results[0].contract_reference,
        evidence_digest: computeEvidenceDigest(run, run.capability_results[0]),
        observation_summary: "The cloud-only boundary was reviewed.",
      },
      output: {
        verdict: "rejected",
        summary: "The deviation has not been accepted.",
      },
      rationale: "The reviewer rejected the proposed deviation.",
      latency_ms: 42,
      recorded_at: "2026-07-29T08:00:00Z",
    },
  };
  for (const disposition of ["rejected", "pending_review"]) {
    run.capability_results[0].intentional_deviation.disposition = disposition;
    run.capability_results[0].intentional_deviation.judgment_audit.output.verdict =
      disposition;
    assert.equal(
      deviationErrors().some((error) =>
        error.includes("intentional_deviation must be accepted"),
      ),
      true,
      disposition,
    );
  }
  run.capability_results[0].intentional_deviation.disposition = "accepted";
  run.capability_results[0].intentional_deviation.judgment_audit.output.verdict =
    "accepted";
  assert.deepEqual(deviationErrors(), []);

  run.capability_results[0].intentional_deviation.judgment_audit.input.contract_reference =
    `${desiredContractRepositoryPath}#different-capability`;
  assert.equal(
    deviationErrors().some((error) => error.includes("contract_reference")),
    true,
  );
});

test("accepted judgments bind the exact run revisions, state and artifact digests", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const reviewedRun = createAcceptedRun("evidence-binding-proof");
  reviewedRun.evidence_profile = "paired_production_renderer";
  reviewedRun.capability_results[0].artifact_ids = ["shared-contract-report"];
  reviewedRun.capability_results[0].parity_judgment.judgment_audit.input.evidence_digest =
    computeEvidenceDigest(reviewedRun, reviewedRun.capability_results[0]);
  const mutations = [
    ["run id", (run) => (run.run_id = "desktop-parity-mutated-run")],
    ["evidence profile", (run) => delete run.evidence_profile],
    [
      "run channel evidence",
      (run) => (run.evidence.browser.summary = "Mutated Browser evidence."),
    ],
    [
      "revision",
      (run) => (run.source_revisions.prototype_revision = "2".repeat(40)),
    ],
    ["environment", (run) => (run.environment.locale = "zh-CN")],
    [
      "source state",
      (run) => (run.source_state.worktree_state = "dirty"),
    ],
    ["started at", (run) => (run.started_at = "2026-07-29T07:59:59Z")],
    ["completed at", (run) => (run.completed_at = "2026-07-29T08:00:01Z")],
    ["matched state", (run) => (run.matched_state.theme = "light")],
    ["artifact hash", (run) => (run.artifacts[0].sha256 = "c".repeat(64))],
    ["artifact channel", (run) => (run.artifacts[0].channel = "build")],
    [
      "artifact role",
      (run) => (run.artifacts[0].evidence_roles = ["native_electron"]),
    ],
  ];
  for (const [label, mutate] of mutations) {
    const changedRun = structuredClone(reviewedRun);
    mutate(changedRun);
    assert.equal(
      validateEvidenceRun(schema, changedRun).some((error) =>
        error.includes("parity_judgment evidence_digest does not match"),
      ),
      true,
      label,
    );
  }

  reviewedRun.artifacts[0].evidence_roles = [
    "web_renderer",
    "desktop_renderer",
  ];
  const expectedDigest = computeEvidenceDigest(
    reviewedRun,
    reviewedRun.capability_results[0],
  );
  reviewedRun.artifacts[0].evidence_roles.reverse();
  assert.equal(
    computeEvidenceDigest(reviewedRun, reviewedRun.capability_results[0]),
    expectedDigest,
  );
  const unreferencedRun = structuredClone(reviewedRun);
  unreferencedRun.artifacts.push({
    ...reviewedRun.artifacts[0],
    artifact_id: "unreferenced-report",
  });
  assert.equal(
    computeEvidenceDigest(
      unreferencedRun,
      unreferencedRun.capability_results[0],
    ),
    expectedDigest,
  );
});

test("capability evidence rejects duplicate capability result identities", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const run = createAcceptedRun("duplicate-capability");
  const duplicate = structuredClone(run.capability_results[0]);
  duplicate.summary = "Different evidence for the same capability identity.";
  run.capability_results.push(duplicate);
  const validation = validateEvidenceRun(schema, run);
  assert.equal(
    validation.some((error) =>
      error.includes("duplicates capability_id duplicate-capability"),
    ),
    true,
  );
});

test("non-passing capability observations still require a real manifest capability reference", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const manifest = readContractJson("parity-manifest.v2.json");
  const unknown = createAcceptedRun("fabricated-capability");
  unknown.capability_results[0].result = "not_run";
  const known = createAcceptedRun(manifest.capabilities[0].id);
  known.capability_results[0].result = "not_run";
  known.capability_results[0].contract_reference =
    `${desiredContractRepositoryPath}#wrong`;
  const unknownErrors = validateEvidenceRun(schema, unknown, { manifest });
  assert.equal(
    unknownErrors.some((error) =>
      error.includes("missing from the desired manifest"),
    ),
    true,
  );
  const referenceErrors = validateEvidenceRun(schema, known, { manifest });
  assert.equal(
    referenceErrors.some((error) =>
      error.includes("contract_reference must equal"),
    ),
    true,
  );
});

test("commit-bound evidence rejects dirty worktrees and mismatched HEAD revisions", () => {
  const schema = readContractJson("evidence-run.v1.schema.json");
  const manifest = readContractJson("parity-manifest.v2.json");
  const run = createAcceptedRun("agent-workspace-tenant-agent-workspace");
  run.source_state.worktree_state = "dirty";
  run.source_state.head_revision = "2222222222222222222222222222222222222222";
  const validation = validateEvidenceRun(schema, run, { manifest });
  assert.equal(
    validation.some(
      (error) =>
        error.includes("source_state.worktree_state") &&
        error.includes("clean"),
    ),
    true,
  );
  assert.equal(
    validation.some(
      (error) =>
        error.includes("source_state.head_revision") &&
        error.includes("repository_revision"),
    ),
    true,
  );
});
