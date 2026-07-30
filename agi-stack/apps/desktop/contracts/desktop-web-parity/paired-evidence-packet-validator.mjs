import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { inflateSync } from "node:zlib";

import {
  inspectEvidenceRepositoryBinding,
  validateEvidenceRun,
} from "./evidence-run-validator.mjs";
import {
  compareObservedLocale,
  requireLocaleRenderingMatch,
} from "./paired-locale-contract.mjs";

const PNG_SIGNATURE = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);
const PAIRED_ROLES = Object.freeze({
  renderer_build_receipt: Object.freeze({
    channel: "build",
    kind: "report",
    mediaType: "application/json",
  }),
  web_full_screenshot: Object.freeze({
    channel: "browser",
    kind: "screenshot",
    mediaType: "image/png",
  }),
  desktop_full_screenshot: Object.freeze({
    channel: "browser",
    kind: "screenshot",
    mediaType: "image/png",
  }),
  visual_diff: Object.freeze({
    channel: "browser",
    kind: "screenshot",
    mediaType: "image/png",
  }),
  observation_metadata: Object.freeze({
    channel: "browser",
    kind: "report",
    mediaType: "application/json",
  }),
});
const MAX_PNG_PIXELS = 50_000_000;
const CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
  }
  return value >>> 0;
});

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function paeth(left, above, upperLeft) {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) {
    return left;
  }
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

export function decodePlaywrightPng(bytes) {
  if (!Buffer.isBuffer(bytes) || !bytes.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error("PNG signature is invalid");
  }
  let offset = 8;
  let ihdr = null;
  let sawIend = false;
  const idatChunks = [];
  while (offset < bytes.length) {
    if (offset + 12 > bytes.length) throw new Error("PNG chunk is truncated");
    const length = bytes.readUInt32BE(offset);
    const chunkEnd = offset + 12 + length;
    if (chunkEnd > bytes.length) throw new Error("PNG chunk is truncated");
    const typeBytes = bytes.subarray(offset + 4, offset + 8);
    const type = typeBytes.toString("ascii");
    const body = bytes.subarray(offset + 8, offset + 8 + length);
    const expectedCrc = bytes.readUInt32BE(offset + 8 + length);
    if (crc32(Buffer.concat([typeBytes, body])) !== expectedCrc) {
      throw new Error(`PNG ${type} CRC is invalid`);
    }
    if (type === "IHDR") {
      if (ihdr !== null || offset !== 8 || length !== 13) {
        throw new Error("PNG must contain one leading IHDR");
      }
      ihdr = body;
    } else if (type === "IDAT") {
      if (ihdr === null || sawIend)
        throw new Error("PNG IDAT order is invalid");
      idatChunks.push(body);
    } else if (type === "IEND") {
      if (length !== 0 || sawIend) throw new Error("PNG IEND is invalid");
      sawIend = true;
      offset = chunkEnd;
      break;
    }
    offset = chunkEnd;
  }
  if (ihdr === null || !sawIend || offset !== bytes.length) {
    throw new Error("PNG structure is incomplete");
  }
  const width = ihdr.readUInt32BE(0);
  const height = ihdr.readUInt32BE(4);
  const bitDepth = ihdr[8];
  const colorType = ihdr[9];
  if (width === 0 || height === 0 || width * height > MAX_PNG_PIXELS) {
    throw new Error("PNG dimensions are unsupported");
  }
  if (bitDepth !== 8) throw new Error("PNG must be 8-bit");
  if (colorType !== 2 && colorType !== 6) {
    throw new Error("PNG must use RGB or RGBA color");
  }
  if (ihdr[10] !== 0 || ihdr[11] !== 0 || ihdr[12] !== 0) {
    throw new Error("PNG compression, filtering, or interlace is unsupported");
  }
  if (idatChunks.length === 0) throw new Error("PNG IDAT is missing");

  const bytesPerPixel = colorType === 6 ? 4 : 3;
  const rowBytes = width * bytesPerPixel;
  const inflatedSize = (rowBytes + 1) * height;
  const inflated = inflateSync(Buffer.concat(idatChunks), {
    maxOutputLength: inflatedSize,
  });
  if (inflated.length !== inflatedSize) {
    throw new Error("PNG decompressed size is invalid");
  }

  const raw = Buffer.alloc(rowBytes * height);
  for (let row = 0; row < height; row += 1) {
    const sourceOffset = row * (rowBytes + 1);
    const filter = inflated[sourceOffset];
    if (filter > 4) throw new Error("PNG row filter is unsupported");
    for (let column = 0; column < rowBytes; column += 1) {
      const source = inflated[sourceOffset + 1 + column];
      const targetOffset = row * rowBytes + column;
      const left =
        column >= bytesPerPixel ? raw[targetOffset - bytesPerPixel] : 0;
      const above = row > 0 ? raw[targetOffset - rowBytes] : 0;
      const upperLeft =
        row > 0 && column >= bytesPerPixel
          ? raw[targetOffset - rowBytes - bytesPerPixel]
          : 0;
      const predictor =
        filter === 0
          ? 0
          : filter === 1
            ? left
            : filter === 2
              ? above
              : filter === 3
                ? Math.floor((left + above) / 2)
                : paeth(left, above, upperLeft);
      raw[targetOffset] = (source + predictor) & 0xff;
    }
  }

  if (colorType === 6) return { width, height, rgba: raw };
  const rgba = Buffer.alloc(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    raw.copy(rgba, pixel * 4, pixel * 3, pixel * 3 + 3);
    rgba[pixel * 4 + 3] = 255;
  }
  return { width, height, rgba };
}

function resolvePacketArtifacts(errors, run, evidenceRunPath) {
  const evidenceRoot = realpathSync(resolve(evidenceRunPath, ".."));
  const artifactsByRole = new Map();
  for (const [role, contract] of Object.entries(PAIRED_ROLES)) {
    const matches = (run.artifacts ?? []).filter((artifact) =>
      artifact?.evidence_roles?.includes(role),
    );
    if (matches.length !== 1) {
      errors.push(`paired profile requires exactly one ${role} artifact`);
      continue;
    }
    const [artifact] = matches;
    if (
      artifact.channel !== contract.channel ||
      artifact.kind !== contract.kind ||
      artifact.media_type !== contract.mediaType ||
      artifact.evidence_roles.length !== 1
    ) {
      errors.push(
        `${role} artifact channel, kind, media type, or role is invalid`,
      );
      continue;
    }
    const candidate = resolve(evidenceRoot, artifact.location);
    const relativePath = relative(evidenceRoot, candidate);
    if (
      relativePath === ".." ||
      relativePath.startsWith(`..${sep}`) ||
      isAbsolute(relativePath)
    ) {
      errors.push(`${role} artifact escapes the evidence directory`);
      continue;
    }
    try {
      artifactsByRole.set(role, {
        artifact,
        bytes: readFileSync(realpathSync(candidate)),
      });
    } catch {
      errors.push(`${role} artifact is unreadable`);
    }
  }
  const allowedBrowserIds = new Set(
    [...artifactsByRole.entries()]
      .filter(([role]) => PAIRED_ROLES[role].channel === "browser")
      .map(([, binding]) => binding.artifact.artifact_id),
  );
  const allBrowserArtifacts = (run.artifacts ?? []).filter(
    (artifact) => artifact?.channel === "browser",
  );
  if (
    allBrowserArtifacts.length !== 4 ||
    allBrowserArtifacts.some(
      (artifact) => !allowedBrowserIds.has(artifact.artifact_id),
    )
  ) {
    errors.push("paired profile rejects arbitrary browser artifacts");
  }
  const browserReferences = run.evidence?.browser?.artifact_ids ?? [];
  if (
    browserReferences.length !== 4 ||
    browserReferences.some(
      (artifactId) =>
        !allowedBrowserIds.has(artifactId) ||
        browserReferences.filter((candidate) => candidate === artifactId)
          .length !== 1,
    )
  ) {
    errors.push(
      "paired browser evidence must reference its four artifacts once",
    );
  }
  const receiptId = artifactsByRole.get("renderer_build_receipt")?.artifact
    .artifact_id;
  if (
    !receiptId ||
    run.evidence?.build?.artifact_ids?.length !== 1 ||
    run.evidence.build.artifact_ids[0] !== receiptId
  ) {
    errors.push("paired build evidence must uniquely reference its receipt");
  }
  for (const [index, result] of (run.capability_results ?? []).entries()) {
    for (const artifactId of [...allowedBrowserIds, receiptId].filter(
      Boolean,
    )) {
      if (
        result.artifact_ids?.filter((candidate) => candidate === artifactId)
          .length !== 1
      ) {
        errors.push(
          `paired capability result ${index} must reference each packet artifact once`,
        );
      }
    }
  }
  return artifactsByRole;
}

function validateObservedState(errors, run, metadata) {
  if (!isDeepStrictEqual(metadata.matched_state, run.matched_state)) {
    errors.push("observation metadata matched_state does not match the run");
  }
  const focusTarget = run.matched_state?.interaction_state?.startsWith(
    "focused:",
  )
    ? run.matched_state.interaction_state.slice("focused:".length)
    : null;
  const normalizedLocales = {};
  for (const runtime of ["web", "desktop"]) {
    const observed = metadata.final_observed_state?.[runtime];
    const expected = run.matched_state;
    try {
      normalizedLocales[runtime] = compareObservedLocale(
        observed?.locale,
        expected?.locale,
      );
    } catch {
      errors.push(`${runtime} observed locale is not bound to matched_state`);
    }
    if (
      !isRecord(observed) ||
      !isRecord(expected) ||
      observed.comparison_locale !==
        normalizedLocales[runtime]?.comparison_locale ||
      observed.theme !== expected.theme ||
      observed.browser_color_scheme !== expected.theme ||
      observed.viewport?.width !== expected.viewport?.width ||
      observed.viewport?.height !== expected.viewport?.height ||
      observed.device_scale_factor !== expected.device_scale_factor ||
      observed.authentication_state !== expected.authentication_state ||
      observed.account_state !== expected.account_state ||
      observed.permission_state !== expected.permission_state ||
      observed.data_state !== expected.data_state ||
      observed.interaction_state !== expected.interaction_state ||
      observed.focus?.target_id !== focusTarget
    ) {
      errors.push(`${runtime} observed state is not bound to matched_state`);
    }
  }
  try {
    requireLocaleRenderingMatch(
      metadata.final_observed_state?.web?.locale_rendering,
      metadata.final_observed_state?.desktop?.locale_rendering,
    );
  } catch {
    errors.push("paired locale-sensitive rendering is not equivalent");
  }
}

function validatePngEvidence(errors, run, bindings, metadata) {
  const expectedWidth =
    run.matched_state?.viewport?.width * run.matched_state?.device_scale_factor;
  const expectedHeight =
    run.matched_state?.viewport?.height *
    run.matched_state?.device_scale_factor;
  if (
    !Number.isSafeInteger(expectedWidth) ||
    !Number.isSafeInteger(expectedHeight) ||
    expectedWidth <= 0 ||
    expectedHeight <= 0
  ) {
    errors.push("matched viewport and DPR do not produce PNG dimensions");
    return;
  }
  const decoded = {};
  for (const role of [
    "web_full_screenshot",
    "desktop_full_screenshot",
    "visual_diff",
  ]) {
    const binding = bindings.get(role);
    if (!binding) continue;
    try {
      decoded[role] = decodePlaywrightPng(binding.bytes);
      if (
        decoded[role].width !== expectedWidth ||
        decoded[role].height !== expectedHeight
      ) {
        errors.push(`${role} IHDR dimensions do not equal viewport times DPR`);
      }
    } catch (error) {
      errors.push(
        `${role} is not a supported Playwright PNG: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  }
  const web = decoded.web_full_screenshot;
  const desktop = decoded.desktop_full_screenshot;
  const diff = decoded.visual_diff;
  if (!web || !desktop || !diff) return;
  let differingPixels = 0;
  let maxChannelDelta = 0;
  const expectedDiff = Buffer.alloc(web.rgba.length);
  for (let offset = 0; offset < web.rgba.length; offset += 4) {
    let pixelDiffers = false;
    for (let channel = 0; channel < 3; channel += 1) {
      const delta = Math.abs(
        web.rgba[offset + channel] - desktop.rgba[offset + channel],
      );
      expectedDiff[offset + channel] = delta;
      maxChannelDelta = Math.max(maxChannelDelta, delta);
      if (delta !== 0) pixelDiffers = true;
    }
    expectedDiff[offset + 3] = 255;
    if (pixelDiffers) differingPixels += 1;
  }
  if (!expectedDiff.equals(diff.rgba)) {
    errors.push("visual_diff PNG does not equal the recomputed pixel diff");
  }
  if (
    metadata.pixel_observation?.differing_pixels !== differingPixels ||
    metadata.pixel_observation?.total_pixels !==
      expectedWidth * expectedHeight ||
    metadata.pixel_observation?.max_channel_delta !== maxChannelDelta
  ) {
    errors.push("pixel observation does not equal the recomputed PNG diff");
  }
}

export function validatePairedEvidencePacketArtifacts(run, evidenceRunPath) {
  const errors = [];
  if (run?.evidence_profile !== "paired_production_renderer") return errors;
  const bindings = resolvePacketArtifacts(errors, run, evidenceRunPath);
  const metadataBinding = bindings.get("observation_metadata");
  if (!metadataBinding) return errors;
  let metadata;
  try {
    metadata = JSON.parse(metadataBinding.bytes.toString("utf8"));
  } catch {
    errors.push("observation_metadata must contain JSON");
    return errors;
  }
  const hashBindings = {
    renderer_build_receipt_sha256: "renderer_build_receipt",
    web_screenshot_sha256: "web_full_screenshot",
    desktop_screenshot_sha256: "desktop_full_screenshot",
    diff_screenshot_sha256: "visual_diff",
  };
  for (const [field, role] of Object.entries(hashBindings)) {
    const binding = bindings.get(role);
    if (
      !binding ||
      metadata.artifacts?.[field] !== sha256(binding.bytes) ||
      binding.artifact.sha256 !== sha256(binding.bytes)
    ) {
      errors.push(`observation metadata ${field} is not bound to ${role}`);
    }
  }
  if (
    metadata.source_revision !== run.source_revisions?.repository_revision ||
    metadata.worktree_state !== "clean"
  ) {
    errors.push("observation metadata source binding is invalid");
  }
  validateObservedState(errors, run, metadata);
  validatePngEvidence(errors, run, bindings, metadata);
  return errors;
}

export function validateEvidencePacket({ repositoryRoot, evidenceRunPath }) {
  if (
    typeof repositoryRoot !== "string" ||
    typeof evidenceRunPath !== "string"
  ) {
    throw new Error("repositoryRoot and evidenceRunPath are required");
  }
  const canonicalRepositoryRoot = realpathSync(repositoryRoot);
  const run = JSON.parse(readFileSync(evidenceRunPath, "utf8"));
  if (run?.record_kind !== "run") {
    return ["paired evidence packet record_kind must be run"];
  }
  if (run.evidence_profile !== "paired_production_renderer") {
    return [
      "paired evidence packet evidence_profile must be paired_production_renderer",
    ];
  }
  const schema = JSON.parse(
    readFileSync(
      resolve(
        canonicalRepositoryRoot,
        "agi-stack/apps/desktop/contracts/desktop-web-parity/evidence-run.v1.schema.json",
      ),
      "utf8",
    ),
  );
  const contractRelativePath = run.desired_contract?.path;
  const repositoryBinding = inspectEvidenceRepositoryBinding({
    repositoryRoot: canonicalRepositoryRoot,
    contractRelativePath,
  });
  const manifest = JSON.parse(
    readFileSync(
      resolve(canonicalRepositoryRoot, contractRelativePath),
      "utf8",
    ),
  );
  const errors = validateEvidenceRun(schema, run, {
    evidenceRunPath,
    manifest,
    repositoryBinding,
    rendererBuildRoots: {
      repository_root: canonicalRepositoryRoot,
      web: resolve(canonicalRepositoryRoot, "web/dist"),
      desktop_renderer: resolve(
        canonicalRepositoryRoot,
        "agi-stack/apps/desktop/out/renderer",
      ),
    },
  });
  errors.push(...validatePairedEvidencePacketArtifacts(run, evidenceRunPath));
  return errors;
}
