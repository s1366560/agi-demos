import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
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
import { dirname, join } from "node:path";
import { deflateSync } from "node:zlib";
import { test } from "node:test";

import {
  createPairedEvidenceMetadata,
  createPairedEvidenceRun,
} from "../browser-qa/paired-production-evidence.mjs";
import {
  createPairedRendererBuildReceipt,
  serializePairedRendererBuildReceipt,
  snapshotRendererTree,
} from "../browser-qa/production-renderer-build-attestation.mjs";
import { validateEvidencePacket } from "../contracts/desktop-web-parity/paired-evidence-packet-validator.mjs";

const desktopRoot = dirname(
  new URL("../package.json", import.meta.url).pathname,
);
const canonicalSchemaBytes = readFileSync(
  join(desktopRoot, "contracts/desktop-web-parity/evidence-run.v1.schema.json"),
);
const PNG_SIGNATURE = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);

function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

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

function encodePng(width, height, pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const rows = [];
  for (let row = 0; row < height; row += 1) {
    rows.push(
      Buffer.from([0]),
      pixels.subarray(row * width * 4, (row + 1) * width * 4),
    );
  }
  return Buffer.concat([
    PNG_SIGNATURE,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(Buffer.concat(rows))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function write(path, bytes) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, bytes);
}

function git(repositoryRoot, args) {
  return execFileSync(
    "git",
    ["-c", "user.name=Parity Test", "-c", "user.email=parity@test", ...args],
    { cwd: repositoryRoot, encoding: "utf8" },
  ).trim();
}

function finalState(matchedState) {
  const common = {
    ...matchedState,
    browser_color_scheme: matchedState.theme,
    focus: {
      target_id: "email_entry",
      tag_name: "input",
      input_type: "email",
    },
  };
  return { web: common, desktop: structuredClone(common) };
}

function createPacketFixture(t) {
  const repositoryRoot = realpathSync(
    mkdtempSync(join(tmpdir(), "paired-packet-repo-")),
  );
  const evidenceRoot = mkdtempSync(join(tmpdir(), "paired-packet-evidence-"));
  t.after(() => {
    rmSync(repositoryRoot, { recursive: true, force: true });
    rmSync(evidenceRoot, { recursive: true, force: true });
  });
  const contractRelativePath =
    "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";
  const schemaRelativePath =
    "agi-stack/apps/desktop/contracts/desktop-web-parity/evidence-run.v1.schema.json";
  const manifest = {
    schema_version: "2.0.0",
    references: {
      prototype_revision: "1".repeat(40),
    },
    capabilities: [{ id: "authentication-and-account-entry" }],
  };
  const contractBytes = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`);
  const webLock = Buffer.from("lockfileVersion: '9.0'\n");
  const desktopLock = Buffer.from("lockfileVersion: '9.0'\n");
  write(join(repositoryRoot, schemaRelativePath), canonicalSchemaBytes);
  write(join(repositoryRoot, contractRelativePath), contractBytes);
  write(join(repositoryRoot, "web/pnpm-lock.yaml"), webLock);
  write(
    join(repositoryRoot, "agi-stack/apps/desktop/pnpm-lock.yaml"),
    desktopLock,
  );
  write(
    join(repositoryRoot, ".gitignore"),
    Buffer.from("/web/dist/\n/agi-stack/apps/desktop/out/\n"),
  );
  git(repositoryRoot, ["init", "-q"]);
  git(repositoryRoot, ["add", "."]);
  git(repositoryRoot, ["commit", "-qm", "test: packet fixture"]);
  const revision = git(repositoryRoot, ["rev-parse", "HEAD"]);
  const headTree = git(repositoryRoot, ["rev-parse", "HEAD^{tree}"]);

  const webOutputRoot = join(repositoryRoot, "web/dist");
  const desktopOutputRoot = join(
    repositoryRoot,
    "agi-stack/apps/desktop/out/renderer",
  );
  write(join(webOutputRoot, "index.html"), Buffer.from("w"));
  write(join(desktopOutputRoot, "index.html"), Buffer.from("d"));

  const receipt = createPairedRendererBuildReceipt({
    sourceRevision: revision,
    headTree,
    invocationNonce: "a".repeat(64),
    repositoryRoot,
    orchestrationStartedAt: "2026-07-30T08:00:00.000Z",
    orchestrationCompletedAt: "2026-07-30T08:00:04.000Z",
    lockfiles: {
      web: {
        path: "web/pnpm-lock.yaml",
        sha256: digest(webLock),
      },
      desktop: {
        path: "agi-stack/apps/desktop/pnpm-lock.yaml",
        sha256: digest(desktopLock),
      },
    },
    builds: {
      web: {
        command: ["corepack", "pnpm", "run", "build"],
        canonical_cwd: join(repositoryRoot, "web"),
        started_at: "2026-07-30T08:00:00.100Z",
        completed_at: "2026-07-30T08:00:01.900Z",
        exit_code: 0,
      },
      desktop_renderer: {
        command: ["corepack", "pnpm", "run", "build:electron"],
        canonical_cwd: join(repositoryRoot, "agi-stack/apps/desktop"),
        started_at: "2026-07-30T08:00:02.000Z",
        completed_at: "2026-07-30T08:00:03.900Z",
        exit_code: 0,
      },
    },
    toolchain: {
      node: "v22",
      web_pnpm: "11.15.1",
      desktop_pnpm: "11.15.1",
      vite_web: "7.3.0",
      electron_vite: "5.0.0",
      electron: "43.2.0",
    },
    outputSnapshots: {
      web: snapshotRendererTree(webOutputRoot),
      desktop_renderer: snapshotRendererTree(desktopOutputRoot),
    },
  });
  const receiptBytes = serializePairedRendererBuildReceipt(receipt);
  const webPixels = Buffer.from([10, 20, 30, 255, 50, 60, 70, 255]);
  const desktopPixels = Buffer.from([10, 10, 40, 255, 40, 60, 70, 255]);
  const diffPixels = Buffer.from([0, 10, 10, 255, 10, 0, 0, 255]);
  const webPng = encodePng(2, 1, webPixels);
  const desktopPng = encodePng(2, 1, desktopPixels);
  const diffPng = encodePng(2, 1, diffPixels);
  const matchedState = {
    locale: "en-US",
    theme: "light",
    viewport: { width: 2, height: 1 },
    device_scale_factor: 1,
    authentication_state: "signed_out",
    account_state: "none",
    permission_state: "public_entry_only",
    data_state: "empty",
    interaction_state: "focused:email_entry",
  };
  const metadata = createPairedEvidenceMetadata({
    scenarioId: "signed-out-entry",
    expectedObservableResult: "Both entries render.",
    sourceRevision: revision,
    worktreeState: "clean",
    matchedState,
    finalObservedState: finalState(matchedState),
    rendererBuildReceipt: receiptBytes,
    webScreenshot: webPng,
    desktopScreenshot: desktopPng,
    diffScreenshot: diffPng,
    webText: "web",
    desktopText: "desktop",
    pixelObservation: {
      differing_pixels: 2,
      total_pixels: 2,
      max_channel_delta: 10,
    },
  });
  const run = createPairedEvidenceRun({
    scenarioId: "signed-out-entry",
    capabilityId: "authentication-and-account-entry",
    sourceRevision: revision,
    contractRevision: revision,
    contractSha256: digest(contractBytes),
    contractPath: contractRelativePath,
    schemaSha256: digest(canonicalSchemaBytes),
    prototypeRevision: revision,
    worktreeState: "clean",
    startedAt: "2026-07-30T08:00:00.000Z",
    browserStartedAt: "2026-07-30T08:00:05.000Z",
    completedAt: "2026-07-30T08:00:10.000Z",
    matchedState,
    metadata,
    rendererBuildReceipt: receipt,
    rendererBuildReceiptBytes: receiptBytes,
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
  const bodies = new Map([
    ["evidence-run.v1.schema.json", canonicalSchemaBytes],
    ["parity-manifest.v2.json", contractBytes],
    ["renderer-build-receipt.json", receiptBytes],
    ["web-screenshot.png", webPng],
    ["desktop-screenshot.png", desktopPng],
    ["visual-diff.png", diffPng],
    [
      "evidence-metadata.json",
      Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`),
    ],
  ]);
  for (const artifact of run.artifacts) {
    write(join(evidenceRoot, artifact.location), bodies.get(artifact.location));
  }
  const evidenceRunPath = join(evidenceRoot, "evidence-run.json");
  write(evidenceRunPath, Buffer.from(`${JSON.stringify(run, null, 2)}\n`));
  return {
    repositoryRoot,
    evidenceRoot,
    evidenceRunPath,
    run,
    metadata,
  };
}

test("self-derived packet validation accepts one canonical receipt and four Browser artifacts", (t) => {
  const fixture = createPacketFixture(t);
  assert.deepEqual(
    validateEvidencePacket({
      repositoryRoot: fixture.repositoryRoot,
      evidenceRunPath: fixture.evidenceRunPath,
    }),
    [],
  );
});

test("full packet validation rejects record-kind or profile downgrade", (t) => {
  for (const field of ["record_kind", "evidence_profile"]) {
    const fixture = createPacketFixture(t);
    delete fixture.run[field];
    write(
      fixture.evidenceRunPath,
      Buffer.from(`${JSON.stringify(fixture.run, null, 2)}\n`),
    );

    const errors = validateEvidencePacket({
      repositoryRoot: fixture.repositoryRoot,
      evidenceRunPath: fixture.evidenceRunPath,
    });
    assert.equal(
      errors.some((error) =>
        error.includes(
          field === "record_kind"
            ? "record_kind must be run"
            : "evidence_profile must be paired_production_renderer",
        ),
      ),
      true,
      `${field} downgrade must fail closed`,
    );
  }
});

test("packet validation recomputes pixels and rejects forged metadata or arbitrary Browser files", (t) => {
  const fixture = createPacketFixture(t);
  const forgedMetadata = structuredClone(fixture.metadata);
  forgedMetadata.pixel_observation.differing_pixels = 0;
  const forgedMetadataBytes = Buffer.from(
    `${JSON.stringify(forgedMetadata, null, 2)}\n`,
  );
  write(
    join(fixture.evidenceRoot, "evidence-metadata.json"),
    forgedMetadataBytes,
  );
  const metadataArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("observation_metadata"),
  );
  metadataArtifact.sha256 = digest(forgedMetadataBytes);
  const arbitraryBytes = Buffer.from("not a screenshot");
  write(join(fixture.evidenceRoot, "browser.txt"), arbitraryBytes);
  fixture.run.artifacts.push({
    artifact_id: "arbitrary-browser-file",
    kind: "report",
    channel: "browser",
    evidence_roles: ["web_renderer"],
    location: "browser.txt",
    media_type: "text/plain",
    sha256: digest(arbitraryBytes),
    produced_at: fixture.run.completed_at,
  });
  write(
    fixture.evidenceRunPath,
    Buffer.from(`${JSON.stringify(fixture.run, null, 2)}\n`),
  );

  const errors = validateEvidencePacket({
    repositoryRoot: fixture.repositoryRoot,
    evidenceRunPath: fixture.evidenceRunPath,
  });
  assert.equal(
    errors.some((error) => error.includes("recomputed PNG diff")),
    true,
  );
  assert.equal(
    errors.some((error) => error.includes("arbitrary browser artifacts")),
    true,
  );
});

test("packet validation rejects a valid but forged screenshot after every hash is updated", (t) => {
  const fixture = createPacketFixture(t);
  const forgedWebPng = encodePng(
    2,
    1,
    Buffer.from([90, 20, 30, 255, 50, 60, 70, 255]),
  );
  write(join(fixture.evidenceRoot, "web-screenshot.png"), forgedWebPng);
  const webArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("web_full_screenshot"),
  );
  webArtifact.sha256 = digest(forgedWebPng);

  const forgedMetadata = structuredClone(fixture.metadata);
  forgedMetadata.artifacts.web_screenshot_sha256 = digest(forgedWebPng);
  const forgedMetadataBytes = Buffer.from(
    `${JSON.stringify(forgedMetadata, null, 2)}\n`,
  );
  write(
    join(fixture.evidenceRoot, "evidence-metadata.json"),
    forgedMetadataBytes,
  );
  const metadataArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("observation_metadata"),
  );
  metadataArtifact.sha256 = digest(forgedMetadataBytes);
  write(
    fixture.evidenceRunPath,
    Buffer.from(`${JSON.stringify(fixture.run, null, 2)}\n`),
  );

  const errors = validateEvidencePacket({
    repositoryRoot: fixture.repositoryRoot,
    evidenceRunPath: fixture.evidenceRunPath,
  });
  assert.equal(
    errors.includes("visual_diff PNG does not equal the recomputed pixel diff"),
    true,
  );
  assert.equal(
    errors.some((error) =>
      error.includes("web_full_screenshot is not a supported Playwright PNG"),
    ),
    false,
  );
});

test("packet validation rejects a valid but forged visual diff after every hash is updated", (t) => {
  const fixture = createPacketFixture(t);
  const forgedDiffPng = encodePng(
    2,
    1,
    Buffer.from([0, 0, 0, 255, 0, 0, 0, 255]),
  );
  write(join(fixture.evidenceRoot, "visual-diff.png"), forgedDiffPng);
  const diffArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("visual_diff"),
  );
  diffArtifact.sha256 = digest(forgedDiffPng);

  const forgedMetadata = structuredClone(fixture.metadata);
  forgedMetadata.artifacts.diff_screenshot_sha256 = digest(forgedDiffPng);
  const forgedMetadataBytes = Buffer.from(
    `${JSON.stringify(forgedMetadata, null, 2)}\n`,
  );
  write(
    join(fixture.evidenceRoot, "evidence-metadata.json"),
    forgedMetadataBytes,
  );
  const metadataArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("observation_metadata"),
  );
  metadataArtifact.sha256 = digest(forgedMetadataBytes);
  write(
    fixture.evidenceRunPath,
    Buffer.from(`${JSON.stringify(fixture.run, null, 2)}\n`),
  );

  const errors = validateEvidencePacket({
    repositoryRoot: fixture.repositoryRoot,
    evidenceRunPath: fixture.evidenceRunPath,
  });
  assert.equal(
    errors.includes("visual_diff PNG does not equal the recomputed pixel diff"),
    true,
  );
});

test("packet validation rejects a non-PNG replacement and forged observed state even when hashes are updated", (t) => {
  const fixture = createPacketFixture(t);
  const replacement = Buffer.from("browser-controlled replacement");
  write(join(fixture.evidenceRoot, "web-screenshot.png"), replacement);
  const webArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("web_full_screenshot"),
  );
  webArtifact.sha256 = digest(replacement);

  const forgedMetadata = structuredClone(fixture.metadata);
  forgedMetadata.artifacts.web_screenshot_sha256 = digest(replacement);
  forgedMetadata.final_observed_state.web.authentication_state = "signed_in";
  const forgedMetadataBytes = Buffer.from(
    `${JSON.stringify(forgedMetadata, null, 2)}\n`,
  );
  write(
    join(fixture.evidenceRoot, "evidence-metadata.json"),
    forgedMetadataBytes,
  );
  const metadataArtifact = fixture.run.artifacts.find((artifact) =>
    artifact.evidence_roles.includes("observation_metadata"),
  );
  metadataArtifact.sha256 = digest(forgedMetadataBytes);
  write(
    fixture.evidenceRunPath,
    Buffer.from(`${JSON.stringify(fixture.run, null, 2)}\n`),
  );

  const errors = validateEvidencePacket({
    repositoryRoot: fixture.repositoryRoot,
    evidenceRunPath: fixture.evidenceRunPath,
  });
  assert.equal(
    errors.some(
      (error) =>
        error.includes("web_full_screenshot") &&
        error.includes("supported Playwright PNG"),
    ),
    true,
  );
  assert.equal(
    errors.some((error) => error.includes("web observed state is not bound")),
    true,
  );
});
