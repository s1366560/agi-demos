import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

export const RENDERER_TREE_DIGEST_CONTRACT = "memstack.renderer-tree.v1";
export const PAIRED_RENDERER_BUILD_RECEIPT_KIND =
  "paired-production-renderer-build-receipt";
export const PAIRED_RENDERER_BUILD_RECEIPT_SCHEMA =
  "./production-renderer-build-attestation.v1.schema.json";

const REVISION_PATTERN = /^[0-9a-f]{40}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/u;
const TOOLCHAIN_KEYS = [
  "node",
  "web_pnpm",
  "desktop_pnpm",
  "vite_web",
  "electron_vite",
  "electron",
];
const OUTPUT_CONTRACTS = Object.freeze({
  web: Object.freeze({
    surface: "web",
    repo_relative_root: "web/dist",
    preview_out_dir: "dist",
    entrypoint: "index.html",
  }),
  desktop_renderer: Object.freeze({
    surface: "desktop_renderer",
    repo_relative_root: "agi-stack/apps/desktop/out/renderer",
    electron_runtime_root: "out/renderer",
    preview_out_dir: "out/renderer",
    entrypoint: "index.html",
  }),
});
const BUILD_CONTRACTS = Object.freeze({
  web: Object.freeze({
    command: Object.freeze(["corepack", "pnpm", "run", "build"]),
    relativeCwd: "web",
  }),
  desktop_renderer: Object.freeze({
    command: Object.freeze([
      "corepack",
      "pnpm",
      "run",
      "build:electron",
    ]),
    relativeCwd: "agi-stack/apps/desktop",
  }),
});

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireNonEmptyString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function normalizeRelativePath(value, label) {
  const path = requireNonEmptyString(value, label).normalize("NFC");
  if (
    path.startsWith("/") ||
    path.endsWith("/") ||
    path.includes("\\") ||
    path.includes("\0") ||
    path
      .split("/")
      .some((segment) => segment === "" || segment === "." || segment === "..")
  ) {
    throw new Error(`${label} must be a normalized relative POSIX path`);
  }
  return path;
}

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function normalizeFileEntries(files) {
  if (!Array.isArray(files)) {
    throw new Error("renderer tree files must be an array");
  }
  const seenPaths = new Set();
  const normalized = files.map((file, index) => {
    if (!isRecord(file)) {
      throw new Error(`renderer tree files[${index}] must be an object`);
    }
    const path = normalizeRelativePath(
      file.path,
      `renderer tree files[${index}].path`,
    );
    if (path !== file.path) {
      throw new Error(
        `renderer tree files[${index}].path must use Unicode NFC`,
      );
    }
    if (seenPaths.has(path)) {
      throw new Error(`renderer tree contains duplicate path ${path}`);
    }
    seenPaths.add(path);
    if (!Number.isSafeInteger(file.size_bytes) || file.size_bytes < 0) {
      throw new Error(
        `renderer tree files[${index}].size_bytes must be a non-negative safe integer`,
      );
    }
    if (typeof file.sha256 !== "string" || !SHA256_PATTERN.test(file.sha256)) {
      throw new Error(
        `renderer tree files[${index}].sha256 must be a SHA-256 digest`,
      );
    }
    return {
      path,
      size_bytes: file.size_bytes,
      sha256: file.sha256,
    };
  });
  return normalized.sort((left, right) => compareUtf8(left.path, right.path));
}

export function computeRendererTreeDigest(files) {
  const entries = normalizeFileEntries(files);
  return `sha256:${sha256(
    Buffer.from(
      JSON.stringify({
        digest_contract: RENDERER_TREE_DIGEST_CONTRACT,
        entries,
      }),
      "utf8",
    ),
  )}`;
}

function pathEscapesRoot(root, candidate) {
  const relativePath = relative(root, candidate);
  return (
    relativePath === ".." ||
    relativePath.startsWith(`..${sep}`) ||
    isAbsolute(relativePath)
  );
}

export function snapshotRendererTree(
  rootPath,
  { expectedEntrypoint = "index.html" } = {},
) {
  if (typeof rootPath !== "string" || !isAbsolute(rootPath)) {
    throw new Error("renderer root must be an absolute path");
  }
  const rootStats = lstatSync(rootPath);
  if (rootStats.isSymbolicLink()) {
    throw new Error("renderer root must not be a symbolic link");
  }
  if (!rootStats.isDirectory()) {
    throw new Error("renderer root must be a directory");
  }
  const canonicalRoot = realpathSync(rootPath);
  const normalizedEntrypoint = normalizeRelativePath(
    expectedEntrypoint,
    "expectedEntrypoint",
  );
  const files = [];
  const seenPaths = new Set();

  function visit(directory, relativeDirectory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const normalizedName = entry.name.normalize("NFC");
      if (
        normalizedName.length === 0 ||
        normalizedName.includes("/") ||
        normalizedName.includes("\\") ||
        normalizedName.includes("\0")
      ) {
        throw new Error("renderer tree contains an invalid path");
      }
      const relativePath = relativeDirectory
        ? `${relativeDirectory}/${normalizedName}`
        : normalizedName;
      if (seenPaths.has(relativePath)) {
        throw new Error(
          `renderer tree contains duplicate normalized path ${relativePath}`,
        );
      }
      seenPaths.add(relativePath);

      const candidate = resolve(directory, entry.name);
      const stats = lstatSync(candidate);
      if (stats.isSymbolicLink()) {
        throw new Error(
          `renderer tree must not contain symbolic links: ${relativePath}`,
        );
      }
      const canonicalCandidate = realpathSync(candidate);
      if (pathEscapesRoot(canonicalRoot, canonicalCandidate)) {
        throw new Error(`renderer tree path escapes its root: ${relativePath}`);
      }
      if (stats.isDirectory()) {
        visit(canonicalCandidate, relativePath);
        continue;
      }
      if (!stats.isFile()) {
        throw new Error(
          `renderer tree must contain only regular files: ${relativePath}`,
        );
      }
      const bytes = readFileSync(canonicalCandidate);
      files.push({
        path: relativePath,
        size_bytes: bytes.byteLength,
        sha256: sha256(bytes),
      });
    }
  }

  visit(canonicalRoot, "");
  const normalizedFiles = normalizeFileEntries(files);
  if (!normalizedFiles.some((file) => file.path === normalizedEntrypoint)) {
    throw new Error(`renderer tree must contain ${normalizedEntrypoint}`);
  }
  return {
    digest_contract: RENDERER_TREE_DIGEST_CONTRACT,
    tree_digest: computeRendererTreeDigest(normalizedFiles),
    file_count: normalizedFiles.length,
    total_bytes: normalizedFiles.reduce(
      (total, file) => total + file.size_bytes,
      0,
    ),
    files: normalizedFiles,
  };
}

function validateToolchain(toolchain) {
  if (!isRecord(toolchain)) return ["toolchain must be an object"];
  const errors = [];
  for (const key of TOOLCHAIN_KEYS) {
    if (typeof toolchain[key] !== "string" || toolchain[key].length === 0) {
      errors.push(`toolchain.${key} must be a non-empty string`);
    }
  }
  for (const key of Object.keys(toolchain)) {
    if (!TOOLCHAIN_KEYS.includes(key)) {
      errors.push(`toolchain.${key} is not allowed`);
    }
  }
  return errors;
}

function normalizeToolchain(toolchain) {
  const errors = validateToolchain(toolchain);
  if (errors.length > 0) throw new Error(errors.join("; "));
  return Object.fromEntries(
    TOOLCHAIN_KEYS.map((key) => [key, toolchain[key]]),
  );
}

function requireRevision(value, label) {
  if (
    typeof value !== "string" ||
    !REVISION_PATTERN.test(value) ||
    value === "0".repeat(40)
  ) {
    throw new Error(`${label} must be a non-placeholder Git revision`);
  }
  return value;
}

function requireSha256(value, label) {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new Error(`${label} must be a SHA-256 digest`);
  }
  return value;
}

function requireTimestamp(value, label) {
  if (
    typeof value !== "string" ||
    !TIMESTAMP_PATTERN.test(value) ||
    !Number.isFinite(Date.parse(value))
  ) {
    throw new Error(`${label} must be a UTC timestamp`);
  }
  return value;
}

function normalizeLockfiles(lockfiles) {
  if (!isRecord(lockfiles)) throw new Error("lockfiles must be an object");
  return Object.fromEntries(
    [
      ["web", "web/pnpm-lock.yaml"],
      ["desktop", "agi-stack/apps/desktop/pnpm-lock.yaml"],
    ].map(([name, expectedPath]) => {
      const lockfile = lockfiles[name];
      if (!isRecord(lockfile) || lockfile.path !== expectedPath) {
        throw new Error(`lockfiles.${name}.path must equal ${expectedPath}`);
      }
      return [
        name,
        {
          path: expectedPath,
          sha256: requireSha256(
            lockfile.sha256,
            `lockfiles.${name}.sha256`,
          ),
        },
      ];
    }),
  );
}

function normalizeBuild(build, name) {
  if (!isRecord(build)) throw new Error(`builds.${name} must be an object`);
  const expected = BUILD_CONTRACTS[name];
  const command = Array.isArray(build.command)
    ? build.command.map((part, index) =>
        requireNonEmptyString(part, `builds.${name}.command[${index}]`),
      )
    : null;
  if (
    command === null ||
    command.length !== expected.command.length ||
    command.some((part, index) => part !== expected.command[index])
  ) {
    throw new Error(
      `builds.${name}.command must equal ${expected.command.join(" ")}`,
    );
  }
  if (!Number.isSafeInteger(build.exit_code)) {
    throw new Error(`builds.${name}.exit_code must be an integer`);
  }
  return {
    command,
    canonical_cwd: requireNonEmptyString(
      build.canonical_cwd,
      `builds.${name}.canonical_cwd`,
    ),
    started_at: requireTimestamp(
      build.started_at,
      `builds.${name}.started_at`,
    ),
    completed_at: requireTimestamp(
      build.completed_at,
      `builds.${name}.completed_at`,
    ),
    exit_code: build.exit_code,
  };
}

function normalizeOutputSnapshot(snapshot, name) {
  if (!isRecord(snapshot)) {
    throw new Error(`outputSnapshots.${name} must be an object`);
  }
  const files = normalizeFileEntries(snapshot.files);
  return {
    digest_contract: snapshot.digest_contract,
    tree_digest: snapshot.tree_digest,
    file_count: snapshot.file_count,
    total_bytes: snapshot.total_bytes,
    files,
  };
}

export function createPairedRendererBuildReceipt({
  sourceRevision,
  headTree,
  invocationNonce,
  repositoryRoot,
  orchestrationStartedAt,
  orchestrationCompletedAt,
  lockfiles,
  builds,
  toolchain,
  outputSnapshots,
}) {
  const canonicalRepositoryRoot = realpathSync(repositoryRoot);
  const receipt = {
    $schema: PAIRED_RENDERER_BUILD_RECEIPT_SCHEMA,
    schema_version: "1.0.0",
    record_kind: PAIRED_RENDERER_BUILD_RECEIPT_KIND,
    source_revision: requireRevision(sourceRevision, "sourceRevision"),
    source_state: {
      worktree_state: "clean",
      head_tree: requireRevision(headTree, "headTree"),
    },
    invocation_nonce: requireSha256(invocationNonce, "invocationNonce"),
    orchestration: {
      canonical_repository_root: canonicalRepositoryRoot,
      started_at: requireTimestamp(
        orchestrationStartedAt,
        "orchestrationStartedAt",
      ),
      completed_at: requireTimestamp(
        orchestrationCompletedAt,
        "orchestrationCompletedAt",
      ),
    },
    lockfiles: normalizeLockfiles(lockfiles),
    toolchain: normalizeToolchain(toolchain),
    builds: {
      web: normalizeBuild(builds?.web, "web"),
      desktop_renderer: normalizeBuild(
        builds?.desktop_renderer,
        "desktop_renderer",
      ),
    },
    outputs: {
      web: {
        ...OUTPUT_CONTRACTS.web,
        ...normalizeOutputSnapshot(outputSnapshots?.web, "web"),
      },
      desktop_renderer: {
        ...OUTPUT_CONTRACTS.desktop_renderer,
        ...normalizeOutputSnapshot(
          outputSnapshots?.desktop_renderer,
          "desktop_renderer",
        ),
      },
    },
  };
  const errors = validatePairedRendererBuildReceipt(receipt, {
    expectedSourceRevision: sourceRevision,
    expectedInvocationNonce: invocationNonce,
    repositoryRoot: canonicalRepositoryRoot,
  });
  if (errors.length > 0) {
    throw new Error(`renderer build receipt is invalid: ${errors.join("; ")}`);
  }
  return receipt;
}

function validateOutput(errors, name, output, contract) {
  if (!isRecord(output)) {
    errors.push(`${name} output is missing`);
    return;
  }
  for (const [field, expectedValue] of Object.entries(contract)) {
    if (output[field] !== expectedValue) {
      errors.push(`${name} ${field} must equal ${expectedValue}`);
    }
  }
  if (output.digest_contract !== RENDERER_TREE_DIGEST_CONTRACT) {
    errors.push(`${name} digest_contract is invalid`);
  }
  let files = null;
  try {
    files = normalizeFileEntries(output.files);
  } catch (error) {
    errors.push(
      `${name} files are invalid: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
  if (!files) return;
  if (output.tree_digest !== computeRendererTreeDigest(files)) {
    errors.push(`${name} tree_digest is invalid`);
  }
  if (output.file_count !== files.length) {
    errors.push(`${name} file_count is invalid`);
  }
  if (
    output.total_bytes !==
    files.reduce((total, file) => total + file.size_bytes, 0)
  ) {
    errors.push(`${name} total_bytes is invalid`);
  }
  if (!files.some((file) => file.path === contract.entrypoint)) {
    errors.push(`${name} files must contain ${contract.entrypoint}`);
  }
}

function validateLiveOutput(errors, name, output, rootPath, contract) {
  if (rootPath === null) return;
  try {
    const live = snapshotRendererTree(rootPath, {
      expectedEntrypoint: contract.entrypoint,
    });
    for (const key of ["tree_digest", "file_count", "total_bytes"]) {
      if (output?.[key] !== live[key]) {
        errors.push(`${name} live ${key.replaceAll("_", " ")} does not match`);
      }
    }
  } catch (error) {
    errors.push(
      `${name} live tree is invalid: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

function validateBuild(errors, receipt, name, repositoryRoot) {
  const build = receipt.builds?.[name];
  if (!isRecord(build)) {
    errors.push(`builds.${name} is missing`);
    return;
  }
  const expected = BUILD_CONTRACTS[name];
  if (
    !Array.isArray(build.command) ||
    build.command.length !== expected.command.length ||
    build.command.some((part, index) => part !== expected.command[index])
  ) {
    errors.push(`builds.${name}.command is invalid`);
  }
  if (build.exit_code !== 0) {
    errors.push(`builds.${name}.exit_code must equal 0`);
  }
  const startedAt = Date.parse(build.started_at);
  const completedAt = Date.parse(build.completed_at);
  if (!Number.isFinite(startedAt) || !Number.isFinite(completedAt)) {
    errors.push(`builds.${name} timestamps are invalid`);
  } else if (completedAt <= startedAt) {
    errors.push(`builds.${name}.completed_at must follow started_at`);
  }
  if (
    repositoryRoot !== null &&
    build.canonical_cwd !==
      resolve(repositoryRoot, expected.relativeCwd)
  ) {
    errors.push(`builds.${name}.canonical_cwd is invalid`);
  }
}

export function validatePairedRendererBuildReceipt(
  receipt,
  {
    expectedSourceRevision = null,
    expectedHeadTree = null,
    expectedInvocationNonce = null,
    expectedLockfiles = null,
    repositoryRoot = null,
    webRoot = null,
    desktopRendererRoot = null,
    now = null,
    maxAgeMs = 10 * 60 * 1000,
  } = {},
) {
  const errors = [];
  if (!isRecord(receipt)) return ["receipt must be an object"];
  if (receipt.$schema !== PAIRED_RENDERER_BUILD_RECEIPT_SCHEMA) {
    errors.push(
      `$schema must equal ${PAIRED_RENDERER_BUILD_RECEIPT_SCHEMA}`,
    );
  }
  if (receipt.schema_version !== "1.0.0") {
    errors.push("schema_version must equal 1.0.0");
  }
  if (receipt.record_kind !== PAIRED_RENDERER_BUILD_RECEIPT_KIND) {
    errors.push(`record_kind must equal ${PAIRED_RENDERER_BUILD_RECEIPT_KIND}`);
  }
  if (
    !REVISION_PATTERN.test(receipt.source_revision ?? "") ||
    receipt.source_revision === "0".repeat(40)
  ) {
    errors.push("source_revision must be a non-placeholder Git revision");
  }
  if (
    expectedSourceRevision !== null &&
    receipt.source_revision !== expectedSourceRevision
  ) {
    errors.push("source_revision does not match the expected revision");
  }
  if (receipt.source_state?.worktree_state !== "clean") {
    errors.push("source_state.worktree_state must equal clean");
  }
  if (!REVISION_PATTERN.test(receipt.source_state?.head_tree ?? "")) {
    errors.push("source_state.head_tree must be a Git tree revision");
  }
  if (
    expectedHeadTree !== null &&
    receipt.source_state?.head_tree !== expectedHeadTree
  ) {
    errors.push("source_state.head_tree does not match repository HEAD");
  }
  if (!SHA256_PATTERN.test(receipt.invocation_nonce ?? "")) {
    errors.push("invocation_nonce must be a 64-character nonce");
  }
  if (
    expectedInvocationNonce !== null &&
    receipt.invocation_nonce !== expectedInvocationNonce
  ) {
    errors.push("invocation_nonce does not match this runner invocation");
  }

  let canonicalRepositoryRoot = null;
  if (repositoryRoot !== null) {
    try {
      canonicalRepositoryRoot = realpathSync(repositoryRoot);
      if (
        receipt.orchestration?.canonical_repository_root !==
        canonicalRepositoryRoot
      ) {
        errors.push(
          "orchestration.canonical_repository_root does not match",
        );
      }
    } catch {
      errors.push("repositoryRoot must resolve to a readable directory");
    }
  }
  const orchestrationStartedAt = Date.parse(
    receipt.orchestration?.started_at,
  );
  const orchestrationCompletedAt = Date.parse(
    receipt.orchestration?.completed_at,
  );
  if (
    !Number.isFinite(orchestrationStartedAt) ||
    !Number.isFinite(orchestrationCompletedAt)
  ) {
    errors.push("orchestration timestamps are invalid");
  } else {
    if (orchestrationCompletedAt <= orchestrationStartedAt) {
      errors.push("orchestration.completed_at must follow started_at");
    }
    if (
      now !== null &&
      (!Number.isFinite(now) ||
        orchestrationCompletedAt > now ||
        now - orchestrationCompletedAt > maxAgeMs)
    ) {
      errors.push("renderer build receipt is not fresh");
    }
  }

  errors.push(...validateToolchain(receipt.toolchain));
  try {
    normalizeLockfiles(receipt.lockfiles);
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  if (isRecord(expectedLockfiles)) {
    for (const name of ["web", "desktop"]) {
      if (
        receipt.lockfiles?.[name]?.sha256 !== expectedLockfiles[name]
      ) {
        errors.push(`lockfiles.${name}.sha256 does not match live lockfile`);
      }
    }
  }
  for (const name of ["web", "desktop_renderer"]) {
    validateBuild(errors, receipt, name, canonicalRepositoryRoot);
    validateOutput(
      errors,
      name,
      receipt.outputs?.[name],
      OUTPUT_CONTRACTS[name],
    );
  }
  const webCompletedAt = Date.parse(receipt.builds?.web?.completed_at);
  const desktopStartedAt = Date.parse(
    receipt.builds?.desktop_renderer?.started_at,
  );
  if (
    Number.isFinite(webCompletedAt) &&
    Number.isFinite(desktopStartedAt) &&
    desktopStartedAt < webCompletedAt
  ) {
    errors.push("desktop renderer build must not overlap the Web build");
  }
  for (const build of [
    receipt.builds?.web,
    receipt.builds?.desktop_renderer,
  ]) {
    const startedAt = Date.parse(build?.started_at);
    const completedAt = Date.parse(build?.completed_at);
    if (
      Number.isFinite(orchestrationStartedAt) &&
      Number.isFinite(orchestrationCompletedAt) &&
      Number.isFinite(startedAt) &&
      Number.isFinite(completedAt) &&
      (startedAt < orchestrationStartedAt ||
        completedAt > orchestrationCompletedAt)
    ) {
      errors.push("build interval must fall within orchestration interval");
    }
  }
  validateLiveOutput(
    errors,
    "web",
    receipt.outputs?.web,
    webRoot,
    OUTPUT_CONTRACTS.web,
  );
  validateLiveOutput(
    errors,
    "desktop_renderer",
    receipt.outputs?.desktop_renderer,
    desktopRendererRoot,
    OUTPUT_CONTRACTS.desktop_renderer,
  );
  return errors;
}

export function serializePairedRendererBuildReceipt(receipt) {
  const errors = validatePairedRendererBuildReceipt(receipt);
  if (errors.length > 0) {
    throw new Error(`renderer build receipt is invalid: ${errors.join("; ")}`);
  }
  return Buffer.from(`${JSON.stringify(receipt, null, 2)}\n`, "utf8");
}
