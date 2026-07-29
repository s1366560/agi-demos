import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  serializePairedRendererBuildReceipt,
  validatePairedRendererBuildReceipt,
} from "../../browser-qa/production-renderer-build-attestation.mjs";
import {
  canonicalRepositoryRelativePath,
  parseBoundJsonArtifact,
  validateArtifactFiles,
  validateBoundReferenceArtifacts,
} from "./evidence-artifact-validator.mjs";
import { validateJsonSchema } from "./schema-validator.mjs";

const PLACEHOLDER_REVISION = "0000000000000000000000000000000000000000";
const PLACEHOLDER_SHA256 = "0".repeat(64);
const EXECUTED_RESULTS = new Set(["passed", "failed", "blocked"]);
const EVIDENCE_CHANNELS = ["build", "browser", "native"];
const REQUIREMENT_CHANNELS = Object.freeze({
  contract: ["build"],
  web_renderer: ["browser"],
  desktop_renderer: ["browser"],
  native_electron: ["native"],
  sidecar_authority: ["native"],
  desktop_bundle: ["build", "native"],
  release_pipeline: ["build", "native"],
});
const ROLE_ALLOWED_CHANNELS = Object.freeze({
  contract: ["build", "shared"],
  paired_renderer_build: ["build"],
  renderer_build_receipt: ["build"],
  web_renderer: ["browser"],
  desktop_renderer: ["browser"],
  web_full_screenshot: ["browser"],
  desktop_full_screenshot: ["browser"],
  visual_diff: ["browser"],
  observation_metadata: ["browser"],
  native_electron: ["native"],
  sidecar_authority: ["native"],
  desktop_bundle: ["build", "native"],
  release_pipeline: ["build", "native"],
});
const PASSING_DEVIATION_DISPOSITIONS = new Set(["none", "accepted"]);

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordArtifactReferences(errors, artifactIds, references, path) {
  if (!Array.isArray(references)) return;
  for (const artifactId of references) {
    if (!artifactIds.has(artifactId)) {
      errors.push(`${path} references unknown artifact ${artifactId}`);
    }
  }
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, nestedValue]) => [key, canonicalize(nestedValue)]),
  );
}

export function computeEvidenceDigest(run, result) {
  const artifactsById = new Map(
    Array.isArray(run?.artifacts)
      ? run.artifacts.map((artifact) => [artifact?.artifact_id, artifact])
      : [],
  );
  const artifactIds = [...new Set(result?.artifact_ids ?? [])].sort();
  const artifacts = artifactIds.map((artifactId) => {
    const artifact = artifactsById.get(artifactId);
    return {
      artifact_id: artifactId,
      sha256: artifact?.sha256 ?? null,
      channel: artifact?.channel ?? null,
      evidence_roles: Array.isArray(artifact?.evidence_roles)
        ? [...new Set(artifact.evidence_roles)].sort()
        : [],
    };
  });
  const evidenceInput = {
    digest_contract: "desktop-parity-capability-evidence/v2",
    run_id: run?.run_id,
    run_scope: run?.run_scope,
    evidence_profile: run?.evidence_profile,
    artifact_location_base: run?.artifact_location_base,
    schema_artifact_id: run?.schema_artifact_id,
    desired_contract: run?.desired_contract,
    source_revisions: run?.source_revisions,
    source_state: run?.source_state,
    started_at: run?.started_at,
    completed_at: run?.completed_at,
    environment: run?.environment,
    matched_state: run?.matched_state,
    evidence: run?.evidence,
    capability_result: {
      capability_id: result?.capability_id,
      contract_reference: result?.contract_reference,
      result: result?.result,
      evidence: result?.evidence,
      artifact_ids: artifactIds,
    },
    artifacts,
  };
  return `sha256:${digest(JSON.stringify(canonicalize(evidenceInput)))}`;
}

export const createCapabilityEvidenceDigest = computeEvidenceDigest;

function validateArtifactRoleChannels(errors, artifacts) {
  for (const [index, artifact] of artifacts.entries()) {
    if (!isRecord(artifact) || !Array.isArray(artifact.evidence_roles))
      continue;
    for (const role of artifact.evidence_roles) {
      const allowedChannels = ROLE_ALLOWED_CHANNELS[role];
      if (allowedChannels && !allowedChannels.includes(artifact.channel)) {
        errors.push(
          `$.artifacts[${index}].evidence_roles role ${role} is incompatible ` +
            `with channel ${artifact.channel}`,
        );
      }
    }
  }
}

function validatePairedRendererBuildEvidence(
  errors,
  run,
  artifacts,
  resolvedArtifactsById,
  rendererBuildRoots,
) {
  if (run.evidence_profile !== "paired_production_renderer") return;

  const hasLiveRendererBuildRoots =
    isRecord(rendererBuildRoots) &&
    typeof rendererBuildRoots.web === "string" &&
    rendererBuildRoots.web.length > 0 &&
    typeof rendererBuildRoots.desktop_renderer === "string" &&
    rendererBuildRoots.desktop_renderer.length > 0;
  if (!hasLiveRendererBuildRoots) {
    errors.push(
      "$.evidence_profile paired_production_renderer requires live renderer build roots",
    );
  }

  const buildArtifacts = artifacts.filter(
    (artifact) =>
      isRecord(artifact) &&
      Array.isArray(artifact.evidence_roles) &&
      artifact.evidence_roles.includes("renderer_build_receipt"),
  );
  if (buildArtifacts.length !== 1) {
    errors.push(
      "$.evidence_profile paired_production_renderer requires exactly one renderer_build_receipt artifact",
    );
    return;
  }
  const [buildArtifact] = buildArtifacts;
  if (
    run.evidence?.build?.status !== "passed" ||
    !run.evidence.build.artifact_ids?.includes(buildArtifact.artifact_id)
  ) {
    errors.push(
      "$.evidence.build must pass and reference the paired renderer build attestation",
    );
  }
  for (const [index, result] of (run.capability_results ?? []).entries()) {
    if (
      result?.evidence?.build !== "passed" ||
      !result?.artifact_ids?.includes(buildArtifact.artifact_id)
    ) {
      errors.push(
        `$.capability_results[${index}] must pass build evidence and reference the paired renderer build attestation`,
      );
    }
  }

  const resolvedBuildArtifact = resolvedArtifactsById.get(
    buildArtifact.artifact_id,
  );
  if (!resolvedBuildArtifact) {
    errors.push(
      "$.evidence.build paired renderer build attestation file is missing",
    );
    return;
  }
  const buildReceiptBytes = readFileSync(resolvedBuildArtifact);
  const buildReceipt = parseBoundJsonArtifact(
    errors,
    buildReceiptBytes,
    "$.evidence.build",
  );
  if (!buildReceipt) return;
  const repositoryRoot =
    typeof rendererBuildRoots?.repository_root === "string"
      ? rendererBuildRoots.repository_root
      : null;
  const expectedHeadTree =
    repositoryRoot === null
      ? null
      : execFileSync("git", ["rev-parse", "HEAD^{tree}"], {
          cwd: repositoryRoot,
          encoding: "utf8",
        }).trim();
  const expectedLockfiles =
    repositoryRoot === null
      ? null
      : {
          web: digest(readFileSync(resolve(repositoryRoot, "web/pnpm-lock.yaml"))),
          desktop: digest(
            readFileSync(
              resolve(
                repositoryRoot,
                "agi-stack/apps/desktop/pnpm-lock.yaml",
              ),
            ),
          ),
        };
  const receiptErrors = validatePairedRendererBuildReceipt(
    buildReceipt,
    {
      expectedSourceRevision: run.source_revisions?.repository_revision,
      expectedHeadTree,
      expectedLockfiles,
      repositoryRoot,
      webRoot: hasLiveRendererBuildRoots ? rendererBuildRoots.web : null,
      desktopRendererRoot:
        hasLiveRendererBuildRoots
          ? rendererBuildRoots.desktop_renderer
          : null,
    },
  );
  for (const error of receiptErrors) {
    errors.push(`$.evidence.build receipt ${error}`);
  }
  if (
    buildArtifact.produced_at !==
    buildReceipt.orchestration?.completed_at
  ) {
    errors.push(
      "$.evidence.build receipt completed_at must equal artifact produced_at",
    );
  }
  try {
    if (
      !serializePairedRendererBuildReceipt(buildReceipt).equals(
        buildReceiptBytes,
      )
    ) {
      errors.push(
        "$.evidence.build receipt bytes must use canonical serialization",
      );
    }
  } catch (error) {
    errors.push(
      `$.evidence.build receipt cannot be serialized: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

function requiredEvidenceRequirements(capability, errors, path) {
  const requirements = [];
  for (const requirement of capability?.evidence_requirements ?? []) {
    const mappedChannels = REQUIREMENT_CHANNELS[requirement];
    if (!mappedChannels) {
      errors.push(
        `${path} declares unknown evidence requirement ${requirement}`,
      );
      continue;
    }
    requirements.push({ requirement, channels: mappedChannels });
  }
  return requirements;
}

function capabilityDeclaresIntentionalDeviation(capability) {
  return Object.values(capability?.surfaces ?? {}).some(
    (surface) =>
      isRecord(surface) &&
      typeof surface.intentional_deviation === "string" &&
      surface.intentional_deviation.length > 0,
  );
}

function validateJudgmentBinding(errors, run, result, judgment, path) {
  if (!isRecord(judgment) || !isRecord(judgment.judgment_audit)) return;
  const audit = judgment.judgment_audit;
  if (audit.output?.verdict !== judgment.disposition) {
    errors.push(`${path} judgment verdict must equal its disposition`);
  }
  if (audit.input?.contract_reference !== result.contract_reference) {
    errors.push(`${path} must audit its contract_reference`);
  }
  if (audit.input?.evidence_digest !== computeEvidenceDigest(run, result)) {
    errors.push(
      `${path} evidence_digest does not match the capability evidence`,
    );
  }
}

export function inspectEvidenceRepositoryBinding({
  repositoryRoot,
  contractRelativePath,
}) {
  const normalizedContractRelativePath =
    canonicalRepositoryRelativePath(contractRelativePath);
  if (!normalizedContractRelativePath) {
    throw new Error(
      "contractRelativePath must be a canonical repository-relative path",
    );
  }
  const headRevision = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
  const worktreeState =
    execFileSync("git", ["status", "--porcelain"], {
      cwd: repositoryRoot,
      encoding: "utf8",
    }).trim().length === 0
      ? "clean"
      : "dirty";
  const workingTreeContract = readFileSync(
    resolve(repositoryRoot, normalizedContractRelativePath),
  );
  let committedContract = null;
  try {
    committedContract = execFileSync(
      "git",
      ["show", `${headRevision}:${normalizedContractRelativePath}`],
      { cwd: repositoryRoot },
    );
  } catch {
    // A new or modified contract cannot produce commit-bound evidence yet.
  }
  return {
    contractRelativePath: normalizedContractRelativePath,
    headRevision,
    worktreeState,
    contractExistsAtHead: committedContract !== null,
    contractSha256:
      committedContract === null ? null : digest(committedContract),
    workingTreeContractSha256: digest(workingTreeContract),
    contractMatchesWorkingTree:
      committedContract !== null &&
      committedContract.equals(workingTreeContract),
  };
}

export function validateEvidenceRun(
  schema,
  value,
  {
    evidenceRunPath = null,
    manifest = null,
    repositoryBinding = null,
    rendererBuildRoots = null,
  } = {},
) {
  const errors = validateJsonSchema(schema, value);
  if (!isRecord(value) || value.record_kind !== "run") return errors;

  const artifacts = Array.isArray(value.artifacts) ? value.artifacts : [];
  const artifactIds = new Set();
  const artifactsById = new Map();
  for (const [index, artifact] of artifacts.entries()) {
    if (!isRecord(artifact) || typeof artifact.artifact_id !== "string")
      continue;
    if (artifactIds.has(artifact.artifact_id)) {
      errors.push(
        `$.artifacts[${index}].artifact_id duplicates ${artifact.artifact_id}`,
      );
    }
    artifactIds.add(artifact.artifact_id);
    artifactsById.set(artifact.artifact_id, artifact);
  }
  validateArtifactRoleChannels(errors, artifacts);

  if (isRecord(value.source_revisions)) {
    for (const [name, revision] of Object.entries(value.source_revisions)) {
      if (revision === PLACEHOLDER_REVISION) {
        errors.push(
          `$.source_revisions.${name} retains a placeholder revision`,
        );
      }
    }
  }
  if (
    isRecord(value.desired_contract) &&
    value.desired_contract.revision === PLACEHOLDER_REVISION
  ) {
    errors.push("$.desired_contract.revision retains a placeholder revision");
  }
  if (
    isRecord(value.desired_contract) &&
    value.desired_contract.sha256 === PLACEHOLDER_SHA256
  ) {
    errors.push("$.desired_contract.sha256 retains a placeholder digest");
  }
  if (
    isRecord(value.desired_contract) &&
    canonicalRepositoryRelativePath(value.desired_contract.path) === null
  ) {
    errors.push(
      "$.desired_contract.path must be a canonical repository-relative path",
    );
  }

  if (value.source_state?.worktree_state !== "clean") {
    errors.push(
      "$.source_state.worktree_state must be clean for a commit-bound run",
    );
  }
  if (
    value.source_state?.head_revision !==
    value.source_revisions?.repository_revision
  ) {
    errors.push(
      "$.source_state.head_revision must equal $.source_revisions.repository_revision",
    );
  }
  for (const surfaceRevision of ["web_revision", "desktop_revision"]) {
    if (
      value.source_revisions?.[surfaceRevision] !==
      value.source_revisions?.repository_revision
    ) {
      errors.push(
        `$.source_revisions.${surfaceRevision} must equal repository_revision`,
      );
    }
  }
  if (
    value.desired_contract?.revision !==
    value.source_revisions?.repository_revision
  ) {
    errors.push(
      "$.desired_contract.revision must equal $.source_revisions.repository_revision",
    );
  }

  if (!repositoryBinding) {
    errors.push("commit-bound evidence requires a live repository binding");
  } else {
    if (repositoryBinding.worktreeState !== "clean") {
      errors.push("repository binding worktree must be clean");
    }
    if (
      repositoryBinding.contractRelativePath !== value.desired_contract?.path
    ) {
      errors.push(
        "$.desired_contract.path does not match the repository binding contract path",
      );
    }
    if (
      repositoryBinding.headRevision !==
      value.source_revisions?.repository_revision
    ) {
      errors.push("repository binding HEAD does not match repository_revision");
    }
    if (!repositoryBinding.contractExistsAtHead) {
      errors.push("desired contract does not exist at repository binding HEAD");
    }
    if (!repositoryBinding.contractMatchesWorkingTree) {
      errors.push(
        "desired contract differs from the contract committed at HEAD",
      );
    }
    if (repositoryBinding.contractSha256 !== value.desired_contract?.sha256) {
      errors.push(
        "desired contract sha256 does not match the committed contract",
      );
    }
  }

  const startedAt = Date.parse(value.started_at);
  const completedAt = Date.parse(value.completed_at);
  if (
    Number.isFinite(startedAt) &&
    Number.isFinite(completedAt) &&
    completedAt < startedAt
  ) {
    errors.push("$.completed_at must not precede $.started_at");
  }
  const resolvedArtifactsById = validateArtifactFiles(
    errors,
    artifacts,
    evidenceRunPath,
    startedAt,
    completedAt,
  );
  const boundManifest = validateBoundReferenceArtifacts(
    errors,
    schema,
    value,
    artifactsById,
    resolvedArtifactsById,
    manifest,
  );
  validatePairedRendererBuildEvidence(
    errors,
    value,
    artifacts,
    resolvedArtifactsById,
    rendererBuildRoots,
  );
  const capabilitiesById = new Map(
    Array.isArray(boundManifest?.capabilities)
      ? boundManifest.capabilities.map((capability) => [
          capability.id,
          capability,
        ])
      : [],
  );
  if (
    boundManifest &&
    value.desired_contract?.schema_version !== boundManifest.schema_version
  ) {
    errors.push(
      "$.desired_contract.schema_version does not match the manifest",
    );
  }

  if (Array.isArray(value.capability_results)) {
    const seenCapabilityIds = new Set();
    for (const [index, result] of value.capability_results.entries()) {
      if (!isRecord(result)) continue;
      if (seenCapabilityIds.has(result.capability_id)) {
        errors.push(
          `$.capability_results[${index}] duplicates capability_id ${result.capability_id}`,
        );
      }
      seenCapabilityIds.add(result.capability_id);
      const capability = capabilitiesById.get(result.capability_id);
      if (boundManifest && !capability) {
        errors.push(
          `$.capability_results[${index}].capability_id is missing from the desired manifest`,
        );
      } else {
        const expectedReference = `${value.desired_contract.path}#${result.capability_id}`;
        if (result.contract_reference !== expectedReference) {
          errors.push(
            `$.capability_results[${index}].contract_reference must equal ${expectedReference}`,
          );
        }
      }
      recordArtifactReferences(
        errors,
        artifactIds,
        result.artifact_ids,
        `$.capability_results[${index}].artifact_ids`,
      );
      for (const channel of EVIDENCE_CHANNELS) {
        const capabilityStatus = result.evidence?.[channel];
        if (!EXECUTED_RESULTS.has(capabilityStatus)) continue;

        const runChannel = value.evidence?.[channel];
        const runStatus = isRecord(runChannel) ? runChannel.status : undefined;
        if (!EXECUTED_RESULTS.has(runStatus)) {
          errors.push(
            `$.capability_results[${index}].evidence.${channel} cannot be ` +
              `${capabilityStatus} because the run channel is ${runStatus ?? "missing"}`,
          );
        } else if (capabilityStatus === "passed" && runStatus !== "passed") {
          errors.push(
            `$.capability_results[${index}].evidence.${channel} cannot be ` +
              `passed because the run channel is ${runStatus}`,
          );
        }

        const hasChannelArtifact =
          Array.isArray(result.artifact_ids) &&
          result.artifact_ids.some(
            (artifactId) => artifactsById.get(artifactId)?.channel === channel,
          );
        if (!hasChannelArtifact) {
          errors.push(
            `$.capability_results[${index}].artifact_ids must reference a ` +
              `${channel} channel artifact when evidence.${channel} is ${capabilityStatus}`,
          );
        }
      }
      validateJudgmentBinding(
        errors,
        value,
        result,
        result.parity_judgment,
        `$.capability_results[${index}].parity_judgment`,
      );
      validateJudgmentBinding(
        errors,
        value,
        result,
        result.intentional_deviation,
        `$.capability_results[${index}].intentional_deviation`,
      );
      if (
        result.result === "passed" &&
        (!isRecord(result.parity_judgment) ||
          result.parity_judgment.disposition !== "accepted")
      ) {
        errors.push(
          `$.capability_results[${index}] cannot pass before parity_judgment is accepted`,
        );
      }
      if (result.result === "passed") {
        if (capability) {
          for (const { requirement, channels } of requiredEvidenceRequirements(
            capability,
            errors,
            `$.capability_results[${index}]`,
          )) {
            for (const channel of channels) {
              if (result.evidence?.[channel] !== "passed") {
                errors.push(
                  `$.capability_results[${index}].evidence.${channel} is required and must be passed`,
                );
              }
              const hasRequirementArtifact =
                Array.isArray(result.artifact_ids) &&
                result.artifact_ids.some((artifactId) => {
                  const artifact = artifactsById.get(artifactId);
                  return (
                    artifact?.channel === channel &&
                    Array.isArray(artifact.evidence_roles) &&
                    artifact.evidence_roles.includes(requirement)
                  );
                });
              if (!hasRequirementArtifact) {
                errors.push(
                  `$.capability_results[${index}].artifact_ids must reference a ` +
                    `${channel} artifact with evidence role ${requirement}`,
                );
              }
            }
          }
        }
        const judgmentAudit = result.parity_judgment?.judgment_audit;
        if (judgmentAudit?.output?.verdict !== "accepted") {
          errors.push(
            `$.capability_results[${index}].parity_judgment judgment verdict must be accepted`,
          );
        }
        const intentionalDeviation = result.intentional_deviation;
        if (
          !PASSING_DEVIATION_DISPOSITIONS.has(
            intentionalDeviation?.disposition,
          ) ||
          (capabilityDeclaresIntentionalDeviation(capability) &&
            intentionalDeviation?.disposition !== "accepted")
        ) {
          errors.push(
            `$.capability_results[${index}].intentional_deviation must be accepted before the capability can pass`,
          );
        }
        if (
          intentionalDeviation?.disposition === "accepted" &&
          intentionalDeviation.judgment_audit?.output?.verdict !== "accepted"
        ) {
          errors.push(
            `$.capability_results[${index}].intentional_deviation judgment verdict must be accepted`,
          );
        }
        if (
          judgmentAudit?.input?.contract_reference !== result.contract_reference
        ) {
          errors.push(
            `$.capability_results[${index}].parity_judgment must audit its contract_reference`,
          );
        }
      }
    }
    if (value.run_scope === "full_manifest") {
      if (!boundManifest) {
        errors.push(
          "$.capability_results full_manifest coverage requires the desired manifest",
        );
      } else {
        const manifestCapabilityIds = new Set(capabilitiesById.keys());
        for (const capabilityId of [...manifestCapabilityIds].sort()) {
          if (!seenCapabilityIds.has(capabilityId)) {
            errors.push(
              "$.capability_results full_manifest coverage is " +
                `missing capability_id ${capabilityId}`,
            );
          }
        }
        for (const capabilityId of [...seenCapabilityIds].sort()) {
          if (!manifestCapabilityIds.has(capabilityId)) {
            errors.push(
              "$.capability_results full_manifest coverage has " +
                `unexpected capability_id ${capabilityId}`,
            );
          }
        }
      }
    }
  }

  if (isRecord(value.evidence)) {
    for (const channel of EVIDENCE_CHANNELS) {
      const evidenceChannel = value.evidence[channel];
      if (!isRecord(evidenceChannel)) continue;
      recordArtifactReferences(
        errors,
        artifactIds,
        evidenceChannel.artifact_ids,
        `$.evidence.${channel}.artifact_ids`,
      );
      if (
        EXECUTED_RESULTS.has(evidenceChannel.status) &&
        Array.isArray(evidenceChannel.artifact_ids) &&
        !evidenceChannel.artifact_ids.some(
          (artifactId) => artifactsById.get(artifactId)?.channel === channel,
        )
      ) {
        errors.push(
          `$.evidence.${channel}.artifact_ids must include a ${channel} channel artifact`,
        );
      }
    }
  }

  return errors;
}
