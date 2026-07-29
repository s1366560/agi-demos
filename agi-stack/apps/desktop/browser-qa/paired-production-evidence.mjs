import { createHash } from "node:crypto";

import {
  serializePairedRendererBuildReceipt,
  validatePairedRendererBuildReceipt,
} from "./production-renderer-build-attestation.mjs";

const SHA_PATTERN = /^[0-9a-f]{40}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const FAILURE_DOMAINS = new Set([
  "runner_setup",
  "renderer_observation",
  "artifact_persistence",
  "evidence_validation",
]);
const RENDERER_OBSERVATION_PHASES = new Set([
  "navigate",
  "drive-matched-interaction",
  "observe-final-state",
  "capture-artifacts",
  "validate-final-state",
  "final-runtime-diagnostics",
]);
const ARTIFACT_PERSISTENCE_PHASES = new Set([
  "attach-artifacts",
  "attach-evidence-run",
  "completed",
]);

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function requireMatchedState(value, scenarioId) {
  if (
    !isRecord(value) ||
    !isRecord(value.viewport) ||
    !Number.isFinite(value.viewport.width) ||
    !Number.isFinite(value.viewport.height) ||
    !Number.isFinite(value.device_scale_factor)
  ) {
    throw new Error(`${scenarioId} must declare a complete matched state`);
  }
  for (const key of [
    "locale",
    "theme",
    "authentication_state",
    "account_state",
    "permission_state",
    "data_state",
    "interaction_state",
  ]) {
    requireString(value[key], `${scenarioId}.${key}`);
  }
  return Object.freeze({
    locale: value.locale,
    theme: value.theme,
    viewport: Object.freeze({
      width: value.viewport.width,
      height: value.viewport.height,
    }),
    device_scale_factor: value.device_scale_factor,
    authentication_state: value.authentication_state,
    account_state: value.account_state,
    permission_state: value.permission_state,
    data_state: value.data_state,
    interaction_state: value.interaction_state,
  });
}

function requireReadyLandmark(value, label) {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  return Object.freeze({
    role: requireString(value.role, `${label}.role`),
    name: requireString(value.name, `${label}.name`),
  });
}

function requireFocusTarget(value, label) {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  return Object.freeze({
    targetId: requireString(value.target_id, `${label}.target_id`),
    role: requireString(value.role, `${label}.role`),
    name: requireString(value.name, `${label}.name`),
  });
}

function requireProbe(value, label) {
  if (
    !isRecord(value) ||
    !isRecord(value.state_attributes) ||
    !isRecord(value.document_theme)
  ) {
    throw new Error(`${label} must be a complete DOM probe`);
  }
  const stateAttributes = {};
  for (const stateKey of [
    "authentication_state",
    "account_state",
    "permission_state",
    "data_state",
  ]) {
    stateAttributes[stateKey] = requireString(
      value.state_attributes[stateKey],
      `${label}.state_attributes.${stateKey}`,
    );
  }
  const documentTheme = {
    attribute: requireString(
      value.document_theme.attribute,
      `${label}.document_theme.attribute`,
    ),
    darkToken: requireString(
      value.document_theme.dark_token,
      `${label}.document_theme.dark_token`,
    ),
    lightToken:
      value.document_theme.light_token === undefined
        ? null
        : requireString(
            value.document_theme.light_token,
            `${label}.document_theme.light_token`,
          ),
    lightWhenTokenAbsent:
      value.document_theme.light_when_token_absent === true,
  };
  if (
    documentTheme.lightToken === null &&
    !documentTheme.lightWhenTokenAbsent
  ) {
    throw new Error(`${label}.document_theme must declare its light state`);
  }
  return Object.freeze({
    rootSelector: requireString(
      value.root_selector,
      `${label}.root_selector`,
    ),
    stateAttributes: Object.freeze(stateAttributes),
    focusTargetAttribute: requireString(
      value.focus_target_attribute,
      `${label}.focus_target_attribute`,
    ),
    documentTheme: Object.freeze(documentTheme),
  });
}

export function buildPairedEvidenceCases(matrix, manifest) {
  if (
    !isRecord(matrix) ||
    matrix.schema_version !== "1.0.0" ||
    matrix.contract_kind !== "paired-production-renderer-evidence" ||
    !Array.isArray(matrix.scenarios)
  ) {
    throw new Error("paired production evidence matrix is invalid");
  }
  if (!isRecord(manifest) || !Array.isArray(manifest.capabilities)) {
    throw new Error("desired parity manifest is invalid");
  }

  const ids = new Set();
  const capabilityIds = new Set(
    manifest.capabilities.map((capability) => capability?.id),
  );
  return matrix.scenarios.map((scenario) => {
    if (!isRecord(scenario)) {
      throw new Error("paired production scenario must be an object");
    }
    const id = requireString(scenario.id, "scenario.id");
    if (ids.has(id))
      throw new Error(`duplicate paired production scenario ${id}`);
    ids.add(id);
    const capabilityId = requireString(
      scenario.capability_id,
      `${id}.capability_id`,
    );
    if (!capabilityIds.has(capabilityId)) {
      throw new Error(
        `${capabilityId} is not declared in the desired manifest`,
      );
    }
    const coverageDisposition = requireString(
      scenario.coverage_disposition,
      `${id}.coverage_disposition`,
    );
    if (coverageDisposition !== "smoke") {
      throw new Error(`${id}.coverage_disposition must be smoke`);
    }
    const executionBoundary = requireString(
      scenario.execution_boundary,
      `${id}.execution_boundary`,
    );
    if (executionBoundary !== "browser_renderer_only") {
      throw new Error(
        `${id}.execution_boundary must be browser_renderer_only`,
      );
    }
    const matchedState = requireMatchedState(scenario.matched_state, id);
    const expectedObservableResult = requireString(
      scenario.expected_observable_result,
      `${id}.expected_observable_result`,
    );
    return Object.freeze({
      id,
      capabilityId,
      coverageDisposition,
      executionBoundary,
      expectedObservableResult,
      web: Object.freeze({
        runtime: "web",
        path: requireString(scenario.web_path, `${id}.web_path`),
        ready: requireReadyLandmark(scenario.web_ready, `${id}.web_ready`),
        focus: requireFocusTarget(scenario.web_focus, `${id}.web_focus`),
        probe: requireProbe(scenario.web_probe, `${id}.web_probe`),
        matchedState,
      }),
      desktop: Object.freeze({
        runtime: "desktop",
        path: requireString(scenario.desktop_path, `${id}.desktop_path`),
        ready: requireReadyLandmark(
          scenario.desktop_ready,
          `${id}.desktop_ready`,
        ),
        focus: requireFocusTarget(
          scenario.desktop_focus,
          `${id}.desktop_focus`,
        ),
        probe: requireProbe(scenario.desktop_probe, `${id}.desktop_probe`),
        matchedState,
      }),
    });
  });
}

export function pairedFailureDomainForPhase(phase) {
  requireString(phase, "phase");
  if (RENDERER_OBSERVATION_PHASES.has(phase)) {
    return "renderer_observation";
  }
  if (ARTIFACT_PERSISTENCE_PHASES.has(phase)) {
    return "artifact_persistence";
  }
  if (phase === "validate-evidence-run") {
    return "evidence_validation";
  }
  return "runner_setup";
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function requireFinalFocus(value, label) {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  return Object.freeze({
    target_id: requireString(value.target_id, `${label}.target_id`),
    tag_name: requireString(value.tag_name, `${label}.tag_name`),
    input_type: requireString(value.input_type, `${label}.input_type`),
  });
}

function requireFinalRuntimeState(value, runtime, matchedState) {
  const label = `${runtime} final observed state`;
  if (
    !isRecord(value) ||
    !isRecord(value.viewport) ||
    !Number.isFinite(value.viewport.width) ||
    !Number.isFinite(value.viewport.height)
  ) {
    throw new Error(`${label} must be complete`);
  }
  const normalized = Object.freeze({
    locale: requireString(value.locale, `${label}.locale`),
    theme: requireString(value.theme, `${label}.theme`),
    browser_color_scheme: requireString(
      value.browser_color_scheme,
      `${label}.browser_color_scheme`,
    ),
    viewport: Object.freeze({
      width: value.viewport.width,
      height: value.viewport.height,
    }),
    device_scale_factor: value.device_scale_factor,
    authentication_state: requireString(
      value.authentication_state,
      `${label}.authentication_state`,
    ),
    account_state: requireString(
      value.account_state,
      `${label}.account_state`,
    ),
    permission_state: requireString(
      value.permission_state,
      `${label}.permission_state`,
    ),
    data_state: requireString(value.data_state, `${label}.data_state`),
    interaction_state: requireString(
      value.interaction_state,
      `${label}.interaction_state`,
    ),
    focus: requireFinalFocus(value.focus, `${label}.focus`),
  });
  const matches =
    normalized.locale === matchedState.locale &&
    normalized.theme === matchedState.theme &&
    normalized.browser_color_scheme === matchedState.theme &&
    normalized.viewport.width === matchedState.viewport.width &&
    normalized.viewport.height === matchedState.viewport.height &&
    normalized.device_scale_factor === matchedState.device_scale_factor &&
    normalized.authentication_state === matchedState.authentication_state &&
    normalized.account_state === matchedState.account_state &&
    normalized.permission_state === matchedState.permission_state &&
    normalized.data_state === matchedState.data_state &&
    normalized.interaction_state === matchedState.interaction_state;
  if (!matches) {
    throw new Error(
      `${runtime} final observed state does not match the declared matched state`,
    );
  }
  return normalized;
}

function requireFinalObservedState(value, scenarioId, matchedState) {
  if (!isRecord(value)) {
    throw new Error(`${scenarioId}.finalObservedState must be an object`);
  }
  return Object.freeze({
    web: requireFinalRuntimeState(value.web, "web", matchedState),
    desktop: requireFinalRuntimeState(value.desktop, "desktop", matchedState),
  });
}

export function createPairedAttemptEvidence({
  scenarioId,
  capabilityId,
  sourceRevision,
  attemptIndex,
  status,
  startedAt,
  completedAt,
  phase,
  failureDomain = null,
  diagnostics,
  finalObservedState,
}) {
  requireString(scenarioId, "scenarioId");
  requireString(capabilityId, "capabilityId");
  if (!SHA_PATTERN.test(sourceRevision)) {
    throw new Error("sourceRevision must be a 40-character Git revision");
  }
  if (!Number.isInteger(attemptIndex) || attemptIndex < 0) {
    throw new Error("attemptIndex must be a non-negative integer");
  }
  if (!["running", "passed", "failed"].includes(status)) {
    throw new Error("status must be running, passed, or failed");
  }
  requireString(startedAt, "startedAt");
  if (completedAt !== null) requireString(completedAt, "completedAt");
  requireString(phase, "phase");
  if (!Array.isArray(diagnostics)) {
    throw new Error("diagnostics must be an array");
  }
  if (status === "failed") {
    if (!FAILURE_DOMAINS.has(failureDomain)) {
      throw new Error(
        "failed attempt failureDomain must be a supported failure domain",
      );
    }
  } else if (failureDomain !== null) {
    throw new Error("non-failed attempt failureDomain must be null");
  }
  const normalizedDiagnostics = diagnostics.map((diagnostic, index) => {
    if (!isRecord(diagnostic)) {
      throw new Error(`diagnostics[${index}] must be an object`);
    }
    return Object.freeze({
      runtime: requireString(
        diagnostic.runtime,
        `diagnostics[${index}].runtime`,
      ),
      channel: requireString(
        diagnostic.channel,
        `diagnostics[${index}].channel`,
      ),
      message_sha256: sha256(
        requireString(diagnostic.message, `diagnostics[${index}].message`),
      ),
    });
  });

  return {
    schema_version: "1.0.0",
    record_kind: "paired-production-attempt",
    attempt_id: `${scenarioId}-attempt-${attemptIndex}`,
    scenario_id: scenarioId,
    capability_id: capabilityId,
    source_revision: sourceRevision,
    status,
    phase,
    failure_domain: failureDomain,
    started_at: startedAt,
    completed_at: completedAt,
    diagnostics: normalizedDiagnostics,
    final_observed_state: finalObservedState ?? null,
  };
}

export function createPairedEvidenceMetadata({
  scenarioId,
  expectedObservableResult,
  sourceRevision,
  worktreeState,
  matchedState,
  finalObservedState,
  rendererBuildReceipt,
  webScreenshot,
  desktopScreenshot,
  diffScreenshot,
  webText,
  desktopText,
  pixelObservation,
}) {
  requireString(scenarioId, "scenarioId");
  requireString(expectedObservableResult, "expectedObservableResult");
  if (!SHA_PATTERN.test(sourceRevision)) {
    throw new Error("sourceRevision must be a 40-character Git revision");
  }
  if (worktreeState !== "clean" && worktreeState !== "dirty") {
    throw new Error("worktreeState must be clean or dirty");
  }
  const normalizedMatchedState = requireMatchedState(matchedState, scenarioId);
  const normalizedFinalObservedState = requireFinalObservedState(
    finalObservedState,
    scenarioId,
    normalizedMatchedState,
  );
  if (!Buffer.isBuffer(rendererBuildReceipt)) {
    throw new Error("rendererBuildReceipt must be a Buffer");
  }
  if (!isRecord(pixelObservation)) {
    throw new Error("pixelObservation must be an object");
  }
  for (const key of [
    "differing_pixels",
    "total_pixels",
    "max_channel_delta",
  ]) {
    if (!Number.isFinite(pixelObservation[key]) || pixelObservation[key] < 0) {
      throw new Error(`pixelObservation.${key} must be a non-negative number`);
    }
  }

  return {
    schema_version: "1.0.0",
    record_kind: "paired-production-observation",
    scenario_id: scenarioId,
    source_revision: sourceRevision,
    worktree_state: worktreeState,
    produced_at: new Date().toISOString(),
    observation_only: true,
    requires_structured_agent_judgment: true,
    judgment_status: "pending_review",
    expected_observable_result: expectedObservableResult,
    matched_state: normalizedMatchedState,
    final_observed_state: normalizedFinalObservedState,
    artifacts: {
      web_screenshot_sha256: sha256(webScreenshot),
      desktop_screenshot_sha256: sha256(desktopScreenshot),
      diff_screenshot_sha256: sha256(diffScreenshot),
      renderer_build_receipt_sha256: sha256(rendererBuildReceipt),
    },
    content: {
      web_visible_text_sha256: sha256(webText),
      desktop_visible_text_sha256: sha256(desktopText),
    },
    pixel_observation: {
      differing_pixels: pixelObservation.differing_pixels,
      total_pixels: pixelObservation.total_pixels,
      max_channel_delta: pixelObservation.max_channel_delta,
    },
  };
}

export function createPairedEvidenceRun({
  scenarioId,
  capabilityId,
  sourceRevision,
  contractRevision,
  contractSha256,
  contractPath,
  schemaSha256,
  prototypeRevision,
  worktreeState,
  startedAt,
  completedAt,
  matchedState,
  metadata,
  rendererBuildReceipt,
  rendererBuildReceiptBytes,
  environment,
  browserStatus = "passed",
  browserStartedAt = startedAt,
}) {
  requireString(scenarioId, "scenarioId");
  requireString(capabilityId, "capabilityId");
  for (const [label, revision] of Object.entries({
    sourceRevision,
    contractRevision,
    prototypeRevision,
  })) {
    if (!SHA_PATTERN.test(revision)) {
      throw new Error(`${label} must be a 40-character Git revision`);
    }
  }
  for (const [label, timestamp] of Object.entries({ startedAt, completedAt })) {
    requireString(timestamp, label);
  }
  if (!SHA256_PATTERN.test(contractSha256)) {
    throw new Error("contractSha256 must be a 64-character SHA-256 digest");
  }
  if (!SHA256_PATTERN.test(schemaSha256)) {
    throw new Error("schemaSha256 must be a 64-character SHA-256 digest");
  }
  requireString(contractPath, "contractPath");
  if (
    contractPath.startsWith("/") ||
    contractPath.startsWith("./") ||
    contractPath.includes("\\") ||
    contractPath.split("/").some((segment) => segment === "..")
  ) {
    throw new Error("contractPath must be a canonical repository-relative path");
  }
  if (worktreeState !== "clean" && worktreeState !== "dirty") {
    throw new Error("worktreeState must be clean or dirty");
  }
  if (browserStatus !== "passed" && browserStatus !== "failed") {
    throw new Error("browserStatus must be passed or failed");
  }
  const normalizedMatchedState = requireMatchedState(matchedState, scenarioId);
  if (
    !isRecord(metadata) ||
    metadata.scenario_id !== scenarioId ||
    metadata.source_revision !== sourceRevision ||
    metadata.judgment_status !== "pending_review" ||
    !isRecord(metadata.artifacts)
  ) {
    throw new Error("paired evidence metadata does not match the evidence run");
  }
  if (!isRecord(environment)) {
    throw new Error("environment must be an object");
  }
  if (!Buffer.isBuffer(rendererBuildReceiptBytes)) {
    throw new Error("rendererBuildReceiptBytes must be a Buffer");
  }
  const buildReceiptErrors = validatePairedRendererBuildReceipt(
    rendererBuildReceipt,
    { expectedSourceRevision: sourceRevision },
  );
  if (buildReceiptErrors.length > 0) {
    throw new Error(
      `rendererBuildReceipt is invalid: ${buildReceiptErrors.join("; ")}`,
    );
  }
  const canonicalBuildReceiptBytes =
    serializePairedRendererBuildReceipt(rendererBuildReceipt);
  if (!canonicalBuildReceiptBytes.equals(rendererBuildReceiptBytes)) {
    throw new Error(
      "rendererBuildReceiptBytes must equal the canonical receipt bytes",
    );
  }

  const schemaArtifactId = `${scenarioId}-evidence-schema`;
  const contractArtifactId = `${scenarioId}-desired-contract`;
  const buildReceiptArtifactId = `${scenarioId}-renderer-build-receipt`;
  const sharedArtifactDefinitions = [
    {
      artifact_id: schemaArtifactId,
      kind: "report",
      evidence_roles: ["contract"],
      location: "evidence-run.v1.schema.json",
      media_type: "application/schema+json",
      sha256: schemaSha256,
    },
    {
      artifact_id: contractArtifactId,
      kind: "report",
      evidence_roles: ["contract"],
      location: contractPath.split("/").at(-1),
      media_type: "application/json",
      sha256: contractSha256,
    },
  ].map((artifact) => ({
    ...artifact,
    channel: "shared",
    produced_at: completedAt,
  }));
  const browserArtifactDefinitions = [
    {
      artifact_id: `${scenarioId}-web-screenshot`,
      kind: "screenshot",
      evidence_roles: ["web_full_screenshot"],
      location: "web-screenshot.png",
      media_type: "image/png",
      sha256: metadata.artifacts.web_screenshot_sha256,
    },
    {
      artifact_id: `${scenarioId}-desktop-screenshot`,
      kind: "screenshot",
      evidence_roles: ["desktop_full_screenshot"],
      location: "desktop-screenshot.png",
      media_type: "image/png",
      sha256: metadata.artifacts.desktop_screenshot_sha256,
    },
    {
      artifact_id: `${scenarioId}-visual-diff`,
      kind: "screenshot",
      evidence_roles: ["visual_diff"],
      location: "visual-diff.png",
      media_type: "image/png",
      sha256: metadata.artifacts.diff_screenshot_sha256,
    },
    {
      artifact_id: `${scenarioId}-observation-metadata`,
      kind: "report",
      evidence_roles: ["observation_metadata"],
      location: "evidence-metadata.json",
      media_type: "application/json",
      sha256: sha256(Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`)),
    },
  ].map((artifact) => ({
    ...artifact,
    channel: "browser",
    produced_at: completedAt,
  }));
  const buildArtifactDefinitions = [
    {
      artifact_id: buildReceiptArtifactId,
      kind: "report",
      channel: "build",
      evidence_roles: ["renderer_build_receipt"],
      location: "renderer-build-receipt.json",
      media_type: "application/json",
      sha256: sha256(rendererBuildReceiptBytes),
      produced_at: rendererBuildReceipt.orchestration.completed_at,
    },
  ];
  const artifactDefinitions = [
    ...sharedArtifactDefinitions,
    ...buildArtifactDefinitions,
    ...browserArtifactDefinitions,
  ];
  const artifactIds = artifactDefinitions.map(
    (artifact) => artifact.artifact_id,
  );
  const browserArtifactIds = browserArtifactDefinitions.map(
    (artifact) => artifact.artifact_id,
  );
  const buildArtifactIds = buildArtifactDefinitions.map(
    (artifact) => artifact.artifact_id,
  );

  return {
    $schema: "./evidence-run.v1.schema.json",
    schema_version: "1.0.0",
    record_kind: "run",
    run_id: `paired-production-${scenarioId}-${sourceRevision.slice(0, 12)}`,
    run_scope: "capability_slice",
    evidence_profile: "paired_production_renderer",
    artifact_location_base: "evidence_run_directory",
    schema_artifact_id: schemaArtifactId,
    desired_contract: {
      path: contractPath,
      path_base: "repository_root",
      artifact_id: contractArtifactId,
      schema_version: "2.0.0",
      revision: contractRevision,
      sha256: contractSha256,
    },
    source_revisions: {
      repository_revision: sourceRevision,
      web_revision: sourceRevision,
      desktop_revision: sourceRevision,
      prototype_revision: prototypeRevision,
    },
    source_state: {
      head_revision: sourceRevision,
      worktree_state: worktreeState,
    },
    started_at: startedAt,
    completed_at: completedAt,
    environment,
    matched_state: normalizedMatchedState,
    capability_results: [
      {
        capability_id: capabilityId,
        contract_reference: `${contractPath}#${capabilityId}`,
        result: browserStatus === "passed" ? "not_run" : "failed",
        summary:
          browserStatus === "passed"
            ? "Production Browser observation passed; structured Agent parity judgment and native Electron evidence remain pending."
            : "Production renderer observation failed; review the retained attempt phase, diagnostics, and artifacts.",
        evidence: {
          build: "passed",
          browser: browserStatus,
          native: "not_run",
        },
        artifact_ids: artifactIds,
        parity_judgment: {
          disposition: "pending_review",
          statement:
            "Review the retained Web, Desktop, and pixel-difference artifacts with a structured Agent tool call.",
          judgment_audit: null,
        },
        intentional_deviation: {
          disposition: "none",
          statement: null,
          judgment_audit: null,
        },
      },
    ],
    artifacts: artifactDefinitions,
    evidence: {
      build: {
        status: "passed",
        command: "corepack pnpm run qa:paired-production",
        started_at: rendererBuildReceipt.orchestration.started_at,
        completed_at: rendererBuildReceipt.orchestration.completed_at,
        summary:
          "The Web production bundle and canonical Electron renderer output are byte-bound by one orchestration receipt.",
        artifact_ids: buildArtifactIds,
      },
      browser: {
        status: browserStatus,
        command:
          "corepack pnpm exec playwright test --config browser-qa/paired-production.playwright.config.mjs",
        started_at: browserStartedAt,
        completed_at: completedAt,
        summary:
          browserStatus === "passed"
            ? "Both production entries rendered without framework overlays or captured runtime errors."
            : "The production renderer observation did not complete cleanly.",
        artifact_ids: browserArtifactIds,
      },
      native: {
        status: "not_run",
        command: "make -C agi-stack run-desktop",
        started_at: null,
        completed_at: null,
        summary: "Native Electron evidence must be recorded separately.",
        artifact_ids: [],
      },
    },
  };
}
