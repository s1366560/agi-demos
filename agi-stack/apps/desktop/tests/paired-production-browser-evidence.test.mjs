import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deflateSync } from "node:zlib";
import { test } from "node:test";

import {
  buildPairedEvidenceCases,
  createPairedAttemptEvidence,
  createPairedEvidenceMetadata,
  createPairedEvidenceRun,
  pairedFailureDomainForPhase,
} from "../browser-qa/paired-production-evidence.mjs";
import {
  createPairedRendererBuildReceipt,
  serializePairedRendererBuildReceipt,
  snapshotRendererTree,
} from "../browser-qa/production-renderer-build-attestation.mjs";
import { validateEvidenceRun } from "../contracts/desktop-web-parity/evidence-run-validator.mjs";
import { validatePairedEvidencePacketArtifacts } from "../contracts/desktop-web-parity/paired-evidence-packet-validator.mjs";

const matrixBytes = readFileSync(
  new URL("../browser-qa/paired-production.matrix.v1.json", import.meta.url),
);
const matrix = JSON.parse(matrixBytes.toString("utf8"));
const evidenceRunSchemaBytes = readFileSync(
  new URL(
    "../contracts/desktop-web-parity/evidence-run.v1.schema.json",
    import.meta.url,
  ),
);
const evidenceRunSchema = JSON.parse(evidenceRunSchemaBytes.toString("utf8"));
const desiredContractBytes = readFileSync(
  new URL(
    "../contracts/desktop-web-parity/parity-manifest.v2.json",
    import.meta.url,
  ),
);
const desiredContract = JSON.parse(desiredContractBytes.toString("utf8"));
const evidenceRunSchemaSha256 = createHash("sha256")
  .update(evidenceRunSchemaBytes)
  .digest("hex");
const desiredContractSha256 = createHash("sha256")
  .update(desiredContractBytes)
  .digest("hex");
const desiredContractRepositoryPath =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";
const configSource = readFileSync(
  new URL(
    "../browser-qa/paired-production.playwright.config.mjs",
    import.meta.url,
  ),
  "utf8",
);
const specSource = readFileSync(
  new URL("../browser-qa/paired-production.spec.mjs", import.meta.url),
  "utf8",
);
const packageJson = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
);
const makefileSource = readFileSync(
  new URL("../../../Makefile", import.meta.url),
  "utf8",
);
const gitignoreSource = readFileSync(
  new URL("../.gitignore", import.meta.url),
  "utf8",
);
const qaLogSource = readFileSync(new URL("../QA.md", import.meta.url), "utf8");
const designQaSource = readFileSync(
  new URL("../design-qa.md", import.meta.url),
  "utf8",
);
const PNG_SIGNATURE = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
    }
  }
  return (value ^ 0xffffffff) >>> 0;
}

function pngChunk(type, body) {
  const typeBytes = Buffer.from(type, "ascii");
  const chunk = Buffer.alloc(body.length + 12);
  chunk.writeUInt32BE(body.length, 0);
  typeBytes.copy(chunk, 4);
  body.copy(chunk, 8);
  chunk.writeUInt32BE(
    crc32(Buffer.concat([typeBytes, body])),
    chunk.length - 4,
  );
  return chunk;
}

function encodeSolidPng(width, height, color) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const row = Buffer.alloc(width * 4);
  for (let offset = 0; offset < row.length; offset += 4) {
    row.set(color, offset);
  }
  const rows = [];
  for (let index = 0; index < height; index += 1) {
    rows.push(Buffer.from([0]), row);
  }
  return Buffer.concat([
    PNG_SIGNATURE,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(Buffer.concat(rows))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function observedStateFor(matchedState) {
  const common = {
    locale: matchedState.locale,
    theme: matchedState.theme,
    browser_color_scheme: matchedState.theme,
    viewport: matchedState.viewport,
    device_scale_factor: matchedState.device_scale_factor,
    authentication_state: matchedState.authentication_state,
    account_state: matchedState.account_state,
    permission_state: matchedState.permission_state,
    data_state: matchedState.data_state,
    interaction_state: matchedState.interaction_state,
  };
  return {
    web: {
      ...common,
      focus: {
        target_id: "email_entry",
        tag_name: "input",
        input_type: "email",
      },
    },
    desktop: {
      ...common,
      focus: {
        target_id: "email_entry",
        tag_name: "input",
        input_type: "email",
      },
    },
  };
}

function writeRendererFixture(root, marker) {
  mkdirSync(join(root, "assets"), { recursive: true });
  writeFileSync(join(root, "index.html"), `<main>${marker}</main>`);
  writeFileSync(
    join(root, "assets", "app.js"),
    `export default ${JSON.stringify(marker)};`,
  );
}

test("paired production matrix locks identical observable state across Web and Desktop", () => {
  const cases = buildPairedEvidenceCases(matrix, desiredContract);

  assert.equal(cases.length >= 1, true);
  for (const pairedCase of cases) {
    assert.match(pairedCase.web.path, /^\//u);
    assert.match(pairedCase.desktop.path, /^\//u);
    assert.deepEqual(
      pairedCase.web.matchedState,
      pairedCase.desktop.matchedState,
    );
    assert.equal(pairedCase.capabilityId.length > 0, true);
    assert.equal(pairedCase.coverageDisposition, "smoke");
    assert.equal(pairedCase.executionBoundary, "browser_renderer_only");
    assert.equal(pairedCase.web.runtime, "web");
    assert.equal(pairedCase.desktop.runtime, "desktop");
  }

  const signedOut = cases.find(
    (pairedCase) => pairedCase.id === "signed-out-entry",
  );
  assert.ok(signedOut);
  assert.equal(signedOut.web.path, "/login");
  assert.equal(signedOut.desktop.path, "/");
  assert.deepEqual(signedOut.web.ready, {
    role: "heading",
    name: "Welcome Back",
  });
  assert.deepEqual(signedOut.desktop.ready, {
    role: "heading",
    name: "Sign in to MemStack",
  });
  assert.deepEqual(signedOut.web.focus, {
    targetId: "email_entry",
    role: "textbox",
    name: "Email",
  });
  assert.deepEqual(signedOut.desktop.focus, {
    targetId: "email_entry",
    role: "textbox",
    name: "Work email",
  });
  assert.equal(
    signedOut.web.matchedState.interaction_state,
    "focused:email_entry",
  );
  assert.equal(signedOut.web.matchedState.authentication_state, "signed_out");
  assert.equal(signedOut.web.matchedState.account_state, "none");
  assert.equal(
    signedOut.web.matchedState.permission_state,
    "public_entry_only",
  );
  assert.doesNotMatch(signedOut.expectedObservableResult, /\bnative\b/u);
});

test("paired production matrix rejects capabilities outside the desired manifest", () => {
  const unknownCapabilityMatrix = structuredClone(matrix);
  unknownCapabilityMatrix.scenarios[0].capability_id = "unknown-capability";

  assert.throws(
    () => buildPairedEvidenceCases(unknownCapabilityMatrix, desiredContract),
    /unknown-capability is not declared in the desired manifest/u,
  );
});

test("paired config previews pre-built production bundles and retains successful evidence", () => {
  assert.match(configSource, /vite preview/u);
  assert.doesNotMatch(configSource, /vite(?:\s+--host|\s+dev)|pnpm run dev/u);
  assert.match(configSource, /webServer:\s*\[/u);
  assert.match(configSource, /retries:\s*0/u);
  assert.match(configSource, /preserveOutput:\s*["']always["']/u);
  assert.match(configSource, /screenshot:\s*["']on["']/u);
  assert.match(configSource, /trace:\s*["']off["']/u);
  assert.doesNotMatch(configSource, /AGISTACK_PAIRED_(?:WEB|DESKTOP)_URL/u);
  assert.doesNotMatch(configSource, /\/qa\//u);
});

test("paired documentation keeps Browser renderer evidence below the native boundary", () => {
  assert.match(qaLogSource, /Chromium renderer-only observation/u);
  assert.match(qaLogSource, /does not launch Electron/u);
  assert.match(designQaSource, /renderer-only run does not launch Electron/u);
  assert.doesNotMatch(
    qaLogSource,
    /bind the exact Web, Desktop,\s*backend, sidecar, and release revisions/u,
  );
});

test("desktop parity gate builds and runs the paired production renderer evidence", () => {
  assert.equal(
    packageJson.scripts["qa:paired-production"],
    "node browser-qa/run-paired-production.mjs",
  );
  assert.match(
    makefileSource,
    /desktop-parity-check:[^\n]*desktop-route-inventory[^\n]*desktop-paired-browser-qa/u,
  );
  assert.match(
    makefileSource,
    /desktop-route-inventory:[\s\S]*node scripts\/web-route-inventory\.mjs/u,
  );
  assert.doesNotMatch(
    makefileSource,
    /desktop-paired-browser-qa:[^\n]*\n(?:\t[^\n]*\n)*\t[^\n]*run build/u,
  );
  assert.match(
    makefileSource,
    /desktop-paired-browser-qa:[\s\S]*AGISTACK_PAIRED_SOURCE_REVISION/u,
  );
  assert.match(
    makefileSource,
    /desktop-paired-browser-qa:[\s\S]*qa:paired-production/u,
  );
  assert.match(
    makefileSource,
    /Paired production renderer smoke passed; native Electron and release evidence remain separate/u,
  );
  assert.doesNotMatch(
    makefileSource,
    /Desktop parity 契约与 Browser QA 验证通过/u,
  );
  assert.match(gitignoreSource, /^browser-qa\/paired-results\/$/mu);
});

test("paired evidence metadata records hashes and arithmetic observations without a verdict", () => {
  const webScreenshot = encodeSolidPng(1, 1, Buffer.from([10, 20, 30, 255]));
  const desktopScreenshot = encodeSolidPng(
    1,
    1,
    Buffer.from([10, 10, 40, 255]),
  );
  const diffScreenshot = encodeSolidPng(1, 1, Buffer.from([0, 10, 10, 255]));
  const metadata = createPairedEvidenceMetadata({
    scenarioId: "signed-out-entry",
    expectedObservableResult:
      "Both production entries render without runtime failure.",
    sourceRevision: "0000000000000000000000000000000000000000",
    worktreeState: "dirty",
    matchedState: matrix.scenarios[0].matched_state,
    finalObservedState: observedStateFor(matrix.scenarios[0].matched_state),
    rendererBuildReceipt: Buffer.from("receipt"),
    webScreenshot,
    desktopScreenshot,
    diffScreenshot,
    webText: "Web login",
    desktopText: "Desktop login",
    pixelObservation: {
      differing_pixels: 42,
      total_pixels: 100,
      max_channel_delta: 127,
    },
  });

  assert.equal(metadata.observation_only, true);
  assert.equal(metadata.requires_structured_agent_judgment, true);
  assert.equal(metadata.judgment_status, "pending_review");
  assert.equal(
    metadata.expected_observable_result,
    "Both production entries render without runtime failure.",
  );
  assert.equal(metadata.worktree_state, "dirty");
  assert.equal(metadata.pixel_observation.differing_pixels, 42);
  assert.match(metadata.artifacts.web_screenshot_sha256, /^[0-9a-f]{64}$/u);
  assert.match(metadata.artifacts.desktop_screenshot_sha256, /^[0-9a-f]{64}$/u);
  assert.match(metadata.artifacts.diff_screenshot_sha256, /^[0-9a-f]{64}$/u);
  assert.match(metadata.content.web_visible_text_sha256, /^[0-9a-f]{64}$/u);
  assert.match(metadata.content.desktop_visible_text_sha256, /^[0-9a-f]{64}$/u);
  assert.deepEqual(
    metadata.final_observed_state,
    observedStateFor(matrix.scenarios[0].matched_state),
  );
  assert.equal(JSON.stringify(metadata).includes("verdict"), false);
});

test("paired evidence metadata rejects a final locale, theme, viewport, DPR, or interaction mismatch", () => {
  const finalObservedState = observedStateFor(
    matrix.scenarios[0].matched_state,
  );
  finalObservedState.desktop.device_scale_factor = 2;
  const screenshot = encodeSolidPng(1, 1, Buffer.from([10, 20, 30, 255]));

  assert.throws(
    () =>
      createPairedEvidenceMetadata({
        scenarioId: "signed-out-entry",
        expectedObservableResult:
          "Both production entries render without runtime failure.",
        sourceRevision: "0000000000000000000000000000000000000000",
        worktreeState: "dirty",
        matchedState: matrix.scenarios[0].matched_state,
        finalObservedState,
        rendererBuildReceipt: Buffer.from("receipt"),
        webScreenshot: screenshot,
        desktopScreenshot: screenshot,
        diffScreenshot: screenshot,
        webText: "Web login",
        desktopText: "Desktop login",
        pixelObservation: {
          differing_pixels: 42,
          total_pixels: 100,
          max_channel_delta: 127,
        },
      }),
    /desktop final observed state does not match the declared matched state/u,
  );
});

test("paired failed attempt evidence records phase and hashed diagnostics without raw messages", () => {
  const attempt = createPairedAttemptEvidence({
    scenarioId: "signed-out-entry",
    capabilityId: "authentication-and-account-entry",
    sourceRevision: "0000000000000000000000000000000000000000",
    attemptIndex: 0,
    status: "failed",
    startedAt: "2026-07-29T08:00:00Z",
    completedAt: "2026-07-29T08:00:30Z",
    phase: "attach-artifacts",
    failureDomain: "artifact_persistence",
    diagnostics: [
      {
        runtime: "desktop",
        channel: "console",
        message: "sensitive provider response",
      },
    ],
    finalObservedState: observedStateFor(matrix.scenarios[0].matched_state),
  });

  assert.equal(attempt.status, "failed");
  assert.equal(attempt.phase, "attach-artifacts");
  assert.equal(attempt.failure_domain, "artifact_persistence");
  assert.equal(attempt.attempt_id, "signed-out-entry-attempt-0");
  assert.equal(attempt.diagnostics[0].runtime, "desktop");
  assert.equal(attempt.diagnostics[0].channel, "console");
  assert.match(attempt.diagnostics[0].message_sha256, /^[0-9a-f]{64}$/u);
  assert.equal(
    JSON.stringify(attempt).includes("sensitive provider response"),
    false,
  );
});

test("paired attempt failure domains keep renderer observations separate from evidence plumbing", () => {
  for (const phase of [
    "navigate",
    "drive-matched-interaction",
    "observe-final-state",
    "capture-artifacts",
    "validate-final-state",
    "final-runtime-diagnostics",
  ]) {
    assert.equal(
      pairedFailureDomainForPhase(phase),
      "renderer_observation",
      phase,
    );
  }
  assert.equal(
    pairedFailureDomainForPhase("attach-artifacts"),
    "artifact_persistence",
  );
  assert.equal(
    pairedFailureDomainForPhase("validate-evidence-run"),
    "evidence_validation",
  );
  assert.equal(
    pairedFailureDomainForPhase("attach-evidence-run"),
    "artifact_persistence",
  );
});

test("paired Browser observation produces a standalone evidence run with pending judgment", (t) => {
  const sourceRevision = "1111111111111111111111111111111111111111";
  const contractSha256 = desiredContractSha256;
  const evidenceRoot = mkdtempSync(
    join(tmpdir(), "paired-production-evidence-"),
  );
  t.after(() => rmSync(evidenceRoot, { recursive: true, force: true }));
  const webRendererRoot = join(evidenceRoot, "build-output", "web");
  const desktopRendererRoot = join(evidenceRoot, "build-output", "desktop");
  writeRendererFixture(webRendererRoot, "web");
  writeRendererFixture(desktopRendererRoot, "desktop");
  const canonicalEvidenceRoot = realpathSync(evidenceRoot);
  const rendererBuildReceipt = createPairedRendererBuildReceipt({
    sourceRevision,
    headTree: "2".repeat(40),
    invocationNonce: "3".repeat(64),
    repositoryRoot: canonicalEvidenceRoot,
    orchestrationStartedAt: "2026-07-29T08:00:00Z",
    orchestrationCompletedAt: "2026-07-29T08:00:15Z",
    lockfiles: {
      web: {
        path: "web/pnpm-lock.yaml",
        sha256: "4".repeat(64),
      },
      desktop: {
        path: "agi-stack/apps/desktop/pnpm-lock.yaml",
        sha256: "5".repeat(64),
      },
    },
    builds: {
      web: {
        command: ["corepack", "pnpm", "run", "build"],
        canonical_cwd: join(canonicalEvidenceRoot, "web"),
        started_at: "2026-07-29T08:00:00.100Z",
        completed_at: "2026-07-29T08:00:05.000Z",
        exit_code: 0,
      },
      desktop_renderer: {
        command: ["corepack", "pnpm", "run", "build:electron"],
        canonical_cwd: join(canonicalEvidenceRoot, "agi-stack/apps/desktop"),
        started_at: "2026-07-29T08:00:06.000Z",
        completed_at: "2026-07-29T08:00:14.000Z",
        exit_code: 0,
      },
    },
    toolchain: {
      node: "v22",
      web_pnpm: "10.24.0",
      desktop_pnpm: "11.15.1",
      vite_web: "7.3.6",
      electron_vite: "5.0.0",
      electron: "43.2.0",
    },
    outputSnapshots: {
      web: snapshotRendererTree(webRendererRoot),
      desktop_renderer: snapshotRendererTree(desktopRendererRoot),
    },
  });
  const rendererBuildReceiptBytes =
    serializePairedRendererBuildReceipt(rendererBuildReceipt);
  const matchedState = matrix.scenarios[0].matched_state;
  const screenshotWidth =
    matchedState.viewport.width * matchedState.device_scale_factor;
  const screenshotHeight =
    matchedState.viewport.height * matchedState.device_scale_factor;
  const webScreenshot = encodeSolidPng(
    screenshotWidth,
    screenshotHeight,
    Buffer.from([10, 20, 30, 255]),
  );
  const desktopScreenshot = encodeSolidPng(
    screenshotWidth,
    screenshotHeight,
    Buffer.from([10, 10, 40, 255]),
  );
  const diffScreenshot = encodeSolidPng(
    screenshotWidth,
    screenshotHeight,
    Buffer.from([0, 10, 10, 255]),
  );
  const totalPixels = screenshotWidth * screenshotHeight;
  const metadata = createPairedEvidenceMetadata({
    scenarioId: "signed-out-entry",
    expectedObservableResult:
      "Both production entries render without runtime failure.",
    sourceRevision,
    worktreeState: "clean",
    matchedState,
    finalObservedState: observedStateFor(matchedState),
    rendererBuildReceipt: rendererBuildReceiptBytes,
    webScreenshot,
    desktopScreenshot,
    diffScreenshot,
    webText: "Web login",
    desktopText: "Desktop login",
    pixelObservation: {
      differing_pixels: totalPixels,
      total_pixels: totalPixels,
      max_channel_delta: 10,
    },
  });
  const run = createPairedEvidenceRun({
    scenarioId: "signed-out-entry",
    capabilityId: "authentication-and-account-entry",
    sourceRevision,
    contractRevision: sourceRevision,
    contractSha256,
    contractPath: desiredContractRepositoryPath,
    schemaSha256: evidenceRunSchemaSha256,
    prototypeRevision: sourceRevision,
    worktreeState: "clean",
    startedAt: "2026-07-29T08:00:00Z",
    completedAt: "2026-07-29T08:01:00Z",
    matchedState,
    metadata,
    rendererBuildReceipt,
    rendererBuildReceiptBytes,
    browserStartedAt: "2026-07-29T08:00:16Z",
    environment: {
      host_os: "test",
      host_os_version: "test",
      architecture: "test",
      execution_context: "local",
      sandboxed: true,
      locale: "en-US",
      timezone: "UTC",
      dependency_versions: {
        node: "v22",
        pnpm: "11.15.1",
        rustc: "rustc test",
        electron: "43.2.0",
      },
    },
  });
  const artifactBodies = new Map([
    ["evidence-run.v1.schema.json", evidenceRunSchemaBytes],
    ["parity-manifest.v2.json", desiredContractBytes],
    ["renderer-build-receipt.json", rendererBuildReceiptBytes],
    ["web-screenshot.png", webScreenshot],
    ["desktop-screenshot.png", desktopScreenshot],
    ["visual-diff.png", diffScreenshot],
    [
      "evidence-metadata.json",
      Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`),
    ],
  ]);
  for (const artifact of run.artifacts) {
    writeFileSync(
      join(evidenceRoot, artifact.location),
      artifactBodies.get(artifact.location),
    );
  }

  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  writeFileSync(
    evidenceRunPath,
    Buffer.from(`${JSON.stringify(run, null, 2)}\n`),
  );
  const validationOptions = {
    evidenceRunPath,
    manifest: desiredContract,
    repositoryBinding: {
      headRevision: sourceRevision,
      worktreeState: "clean",
      contractExistsAtHead: true,
      contractSha256,
      workingTreeContractSha256: contractSha256,
      contractMatchesWorkingTree: true,
      contractRelativePath: desiredContractRepositoryPath,
    },
    rendererBuildRoots: {
      web: webRendererRoot,
      desktop_renderer: desktopRendererRoot,
    },
  };
  assert.deepEqual(
    [
      ...validateEvidenceRun(evidenceRunSchema, run, validationOptions),
      ...validatePairedEvidencePacketArtifacts(run, evidenceRunPath),
    ],
    [],
  );
  const validationWithoutLiveRoots = structuredClone(validationOptions);
  delete validationWithoutLiveRoots.rendererBuildRoots;
  assert.equal(
    validateEvidenceRun(
      evidenceRunSchema,
      run,
      validationWithoutLiveRoots,
    ).some((error) =>
      error.includes(
        "$.evidence_profile paired_production_renderer requires live renderer build roots",
      ),
    ),
    true,
  );
  assert.equal(run.record_kind, "run");
  assert.equal(run.run_scope, "capability_slice");
  assert.deepEqual(run.source_state, {
    head_revision: sourceRevision,
    worktree_state: "clean",
  });
  assert.equal(run.desired_contract.revision, sourceRevision);
  assert.equal(run.desired_contract.sha256, contractSha256);
  assert.equal(run.desired_contract.path_base, "repository_root");
  assert.equal(run.desired_contract.path, desiredContractRepositoryPath);
  assert.equal(run.artifact_location_base, "evidence_run_directory");
  assert.equal(
    run.artifacts.find(
      (artifact) => artifact.artifact_id === run.schema_artifact_id,
    )?.location,
    "evidence-run.v1.schema.json",
  );
  assert.equal(
    run.artifacts.find(
      (artifact) => artifact.artifact_id === run.desired_contract.artifact_id,
    )?.location,
    "parity-manifest.v2.json",
  );
  assert.equal(run.capability_results[0].result, "not_run");
  assert.equal(run.capability_results[0].evidence.build, "passed");
  assert.equal(
    run.capability_results[0].parity_judgment.disposition,
    "pending_review",
  );
  assert.equal(run.evidence.browser.status, "passed");
  assert.equal(run.evidence.build.status, "passed");
  assert.equal(run.evidence.build.artifact_ids.length, 1);
  const buildArtifact = run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("renderer_build_receipt"),
  );
  assert.ok(buildArtifact);
  assert.equal(buildArtifact.channel, "build");
  assert.equal(run.evidence.build.artifact_ids[0], buildArtifact.artifact_id);
  assert.equal(
    run.capability_results[0].artifact_ids.includes(buildArtifact.artifact_id),
    true,
  );
  assert.equal(run.evidence.native.status, "not_run");
  assert.equal(
    run.evidence.browser.command,
    "corepack pnpm exec playwright test --config browser-qa/paired-production.playwright.config.mjs",
  );
});

test("paired spec captures both surfaces, creates a diff PNG, and attaches every artifact", () => {
  assert.match(
    specSource,
    /AGISTACK_PAIRED_SOURCE_REVISION must pin this evidence run to one commit/u,
  );
  assert.doesNotMatch(specSource, /test\.skip/u);
  assert.doesNotMatch(specSource, /AGISTACK_PAIRED_(?:WEB|DESKTOP)_URL/u);
  assert.match(specSource, /expectedReady/u);
  assert.match(specSource, /getByRole\(expectedReady\.role/u);
  assert.match(specSource, /toHaveCount\(1\)/u);
  assert.match(specSource, /toBeVisible\(\)/u);
  assert.match(specSource, /web-screenshot\.png/u);
  assert.match(specSource, /desktop-screenshot\.png/u);
  assert.match(specSource, /visual-diff\.png/u);
  assert.match(specSource, /evidence-metadata\.json/u);
  assert.match(specSource, /renderer-build-receipt\.json/u);
  assert.match(specSource, /AGISTACK_PAIRED_BUILD_RECEIPT/u);
  assert.doesNotMatch(specSource, /createPairedRendererBuildAttestation/u);
  assert.match(specSource, /evidence-run\.json/u);
  assert.match(specSource, /createVisualDiff/u);
  assert.match(specSource, /validatePairedRendererBuildReceipt/u);
  assert.match(specSource, /pageerror/u);
  assert.match(specSource, /console/u);
  assert.match(specSource, /driveMatchedInteractionState/u);
  assert.match(specSource, /observeFinalMatchedState/u);
  assert.doesNotMatch(
    specSource,
    /\.filter\(\{\s*visible:\s*true\s*\}\)\.first\(\)/u,
  );
  assert.doesNotMatch(specSource, /webview|openExternal|window\.open/u);
});

test("paired spec writes declared artifacts before live evidence validation", () => {
  const artifactWriteIndex = specSource.indexOf(
    "writeFileSync(outputPath, body)",
  );
  const liveValidationIndex = specSource.indexOf("validateEvidencePacket({");

  assert.equal(artifactWriteIndex >= 0, true);
  assert.equal(liveValidationIndex > artifactWriteIndex, true);
  assert.match(specSource, /evidenceRunPath:\s*evidenceRunOutputPath/u);
  assert.doesNotMatch(specSource, /evidenceRoot:\s*testInfo\.outputDir/u);
});

test("paired spec persists failed attempt evidence and only records pass after final diagnostics and attachments", () => {
  const contextCloseIndex = specSource.indexOf(
    "Promise.all([webContext.close(), desktopContext.close()])",
  );
  const finalRuntimeDiagnosticIndex = specSource.indexOf(
    "if (runtimeErrors.length > 0)",
  );
  const artifactAttachmentIndex = specSource.indexOf(
    "await testInfo.attach(name",
  );
  const passedRunIndex = specSource.search(/browserStatus:\s*["']passed["']/u);

  assert.equal(contextCloseIndex >= 0, true);
  assert.equal(finalRuntimeDiagnosticIndex > contextCloseIndex, true);
  assert.equal(artifactAttachmentIndex > finalRuntimeDiagnosticIndex, true);
  assert.equal(passedRunIndex > artifactAttachmentIndex, true);
  assert.match(specSource, /attempt-evidence\.json/u);
  assert.match(specSource, /catch \(error\)[\s\S]*status:\s*["']failed["']/u);
  assert.doesNotMatch(
    specSource,
    /catch \(error\)[\s\S]*browserStatus:\s*["']failed["']/u,
  );
  assert.match(
    specSource,
    /catch \(error\)[\s\S]*browserStatus:\s*browserObservationStatus/u,
  );
});
