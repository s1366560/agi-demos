import { randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fchmodSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { isDeepStrictEqual } from "node:util";

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function dispositionSummary(surface) {
  return {
    disposition: surface.disposition,
    implementation_status: surface.implementation_status,
    availability: surface.availability,
    reason_code: surface.reason_code,
    authority: surface.authority,
  };
}

function isWithin(parentPath, candidatePath) {
  const relativePath = relative(parentPath, candidatePath);
  return (
    relativePath === "" ||
    (relativePath !== ".." &&
      !relativePath.startsWith(`..${sep}`) &&
      !isAbsolute(relativePath))
  );
}

function lstatIfPresent(path) {
  try {
    return lstatSync(path);
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function assertCurrentOwner(label, stats) {
  const currentUid = process.getuid?.();
  if (currentUid !== undefined && stats.uid !== currentUid) {
    throw new Error(`${label} must be owned by the current user.`);
  }
}

function assertRegularTarget(label, path, { ownerOnly = false } = {}) {
  const stats = lstatSync(path);
  if (stats.isSymbolicLink()) {
    throw new Error(`${label} must not be a symbolic link.`);
  }
  if (!stats.isFile()) {
    throw new Error(`${label} must be a regular file.`);
  }
  assertCurrentOwner(label, stats);
  if (ownerOnly && (stats.mode & 0o077) !== 0) {
    throw new Error(`${label} must be readable only by its owner (mode 0600).`);
  }
  if (ownerOnly && (stats.mode & 0o400) === 0) {
    throw new Error(`${label} must be readable by its owner.`);
  }
  if (ownerOnly && stats.nlink !== 1) {
    throw new Error(`${label} must not use a hard link.`);
  }
  return stats;
}

function assertAbsolutePath(label, path) {
  if (!isAbsolute(path)) {
    throw new Error(`${label} must use an absolute repository-external path.`);
  }
}

function assertOutsideRepository(label, candidatePath, repositoryRoot) {
  if (isWithin(realpathSync(repositoryRoot), candidatePath)) {
    throw new Error(`${label} must remain outside the repository.`);
  }
}

function resolveRealParentTarget(label, path) {
  const parentPath = realpathSync(dirname(path));
  const parentStats = statSync(parentPath);
  if (!parentStats.isDirectory()) {
    throw new Error(`${label} parent must be a real directory.`);
  }
  return join(parentPath, basename(path));
}

function validateJudgmentPath(path, repositoryRoot) {
  assertAbsolutePath("--judgments", path);
  assertRegularTarget("--judgments", path, { ownerOnly: true });
  const realPath = realpathSync(path);
  assertOutsideRepository("--judgments", realPath, repositoryRoot);
  return realPath;
}

function validateExternalOutputPath(label, path, repositoryRoot) {
  assertAbsolutePath(label, path);
  const realTarget = resolveRealParentTarget(label, path);
  assertOutsideRepository(label, realTarget, repositoryRoot);
  const existing = lstatIfPresent(realTarget);
  if (existing) {
    if (existing.isSymbolicLink()) {
      throw new Error(`${label} target must not be a symbolic link.`);
    }
    if (!existing.isFile()) {
      throw new Error(`${label} target must be a regular file.`);
    }
    assertCurrentOwner(`${label} target`, existing);
  }
  return realTarget;
}

function validateManifestOutputPath(path, manifestPath, repositoryRoot) {
  const resolvedPath = resolve(path);
  const resolvedManifestPath = resolve(manifestPath);
  if (resolvedPath !== resolvedManifestPath) {
    if (!isAbsolute(path)) {
      throw new Error(
        "--output outside the repository must use an absolute path.",
      );
    }
    const realTarget = resolveRealParentTarget("--output", resolvedPath);
    if (isWithin(realpathSync(repositoryRoot), realTarget)) {
      throw new Error(
        "--output inside the repository must be the exact manifest target.",
      );
    }
    return {
      outputOwnerOnly: true,
      outputPath: validateExternalOutputPath(
        "--output",
        resolvedPath,
        repositoryRoot,
      ),
    };
  }
  const realTarget = resolveRealParentTarget(
    "manifest output",
    resolvedManifestPath,
  );
  if (!isWithin(realpathSync(repositoryRoot), realTarget)) {
    throw new Error(
      "The exact manifest target must remain inside the repository.",
    );
  }
  const existing = lstatIfPresent(realTarget);
  if (existing?.isSymbolicLink()) {
    throw new Error("The exact manifest target must not be a symbolic link.");
  }
  if (existing && !existing.isFile()) {
    throw new Error("The exact manifest target must be a regular file.");
  }
  return { outputOwnerOnly: false, outputPath: realTarget };
}

function optionPath(args, index, label) {
  const value = args[index + 1];
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.startsWith("--")
  ) {
    throw new Error(`${label} requires a path argument.`);
  }
  return value;
}

export function parseManifestGeneratorOptions(
  args,
  { manifestPath, repositoryRoot },
) {
  let check = false;
  let judgmentsArgument = null;
  let outputArgument = null;
  let emitInputsArgument = null;
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--check") {
      if (check) throw new Error("--check may only be specified once.");
      check = true;
      continue;
    }
    if (argument === "--judgments") {
      if (judgmentsArgument !== null) {
        throw new Error("--judgments may only be specified once.");
      }
      judgmentsArgument = optionPath(args, index, "--judgments");
      index += 1;
      continue;
    }
    if (argument === "--output") {
      if (outputArgument !== null)
        throw new Error("--output may only be specified once.");
      outputArgument = optionPath(args, index, "--output");
      index += 1;
      continue;
    }
    if (argument === "--emit-inputs") {
      if (emitInputsArgument !== null) {
        throw new Error("--emit-inputs may only be specified once.");
      }
      emitInputsArgument = optionPath(args, index, "--emit-inputs");
      index += 1;
      continue;
    }
    throw new Error(`Unknown argument ${argument}.`);
  }
  if (
    Number(check) +
      Number(judgmentsArgument !== null) +
      Number(emitInputsArgument !== null) !==
    1
  ) {
    throw new Error(
      "Choose exactly one of --check, --judgments, or --emit-inputs.",
    );
  }
  if (outputArgument !== null && judgmentsArgument === null) {
    throw new Error("--output is only valid with --judgments.");
  }
  const judgmentsPath =
    judgmentsArgument === null
      ? null
      : validateJudgmentPath(judgmentsArgument, repositoryRoot);
  const emitInputsPath =
    emitInputsArgument === null
      ? null
      : validateExternalOutputPath(
          "--emit-inputs",
          emitInputsArgument,
          repositoryRoot,
        );
  const { outputOwnerOnly, outputPath } = validateManifestOutputPath(
    outputArgument ?? manifestPath,
    manifestPath,
    repositoryRoot,
  );
  return {
    check,
    emitInputsPath,
    judgmentsPath,
    outputOwnerOnly,
    outputPath,
  };
}

function readProtectedJudgments(path, repositoryRoot) {
  const expectedStats = assertRegularTarget("--judgments", path, {
    ownerOnly: true,
  });
  assertOutsideRepository("--judgments", realpathSync(path), repositoryRoot);
  const descriptor = openSync(
    path,
    constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0),
  );
  try {
    const stats = fstatSync(descriptor);
    if (!stats.isFile()) throw new Error("--judgments must be a regular file.");
    if (stats.dev !== expectedStats.dev || stats.ino !== expectedStats.ino) {
      throw new Error("--judgments changed while it was being opened.");
    }
    assertCurrentOwner("--judgments", stats);
    if (stats.nlink !== 1) {
      throw new Error("--judgments must not use a hard link.");
    }
    if ((stats.mode & 0o077) !== 0 || (stats.mode & 0o400) === 0) {
      throw new Error(
        "--judgments must be readable only by its owner (mode 0600).",
      );
    }
    return readFileSync(descriptor, "utf8");
  } finally {
    closeSync(descriptor);
  }
}

export function loadJudgmentRecords(options, { manifestPath, repositoryRoot }) {
  if (options.check) {
    const checkedInManifest = readJson(manifestPath);
    return checkedInManifest.capabilities.map(
      (capability) => capability.judgment,
    );
  }
  const source = readProtectedJudgments(options.judgmentsPath, repositoryRoot);
  return source
    .split(/\r?\n/u)
    .filter((line) => line.trim().length > 0)
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch (error) {
        throw new Error(`Invalid judgment JSONL record at line ${index + 1}.`, {
          cause: error,
        });
      }
    });
}

export function indexJudgmentRecords(records, expectedCapabilityIds) {
  const expected = new Set(expectedCapabilityIds);
  const indexed = new Map();
  for (const [index, record] of records.entries()) {
    const capabilityId = record?.input?.capability_id;
    if (typeof capabilityId !== "string" || capabilityId.length === 0) {
      throw new Error(
        `Judgment record ${index + 1} lacks input.capability_id.`,
      );
    }
    if (indexed.has(capabilityId)) {
      throw new Error(
        `Judgment records contain duplicate capability ${capabilityId}.`,
      );
    }
    if (!expected.has(capabilityId)) {
      throw new Error(
        `Judgment records contain unexpected capability ${capabilityId}.`,
      );
    }
    indexed.set(capabilityId, record);
  }
  for (const capabilityId of expected) {
    if (!indexed.has(capabilityId)) {
      throw new Error(
        `Judgment records are missing capability ${capabilityId}.`,
      );
    }
  }
  return indexed;
}

export function writeValidatedArtifactSync(
  path,
  contents,
  { ownerOnly = false } = {},
) {
  if (!isAbsolute(path)) {
    throw new Error("Artifact output path must be absolute.");
  }
  const targetPath = resolveRealParentTarget("artifact output", path);
  const existing = lstatIfPresent(targetPath);
  if (existing?.isSymbolicLink()) {
    throw new Error("Artifact output target must not be a symbolic link.");
  }
  if (existing && !existing.isFile()) {
    throw new Error("Artifact output target must be a regular file.");
  }
  if (existing) assertCurrentOwner("Artifact output target", existing);

  const mode = ownerOnly ? 0o600 : (existing?.mode ?? 0o644) & 0o777;
  const temporaryPath = join(
    dirname(targetPath),
    `.${basename(targetPath)}.${process.pid}.${randomUUID()}.tmp`,
  );
  let descriptor;
  try {
    descriptor = openSync(
      temporaryPath,
      constants.O_WRONLY |
        constants.O_CREAT |
        constants.O_EXCL |
        (constants.O_NOFOLLOW ?? 0),
      mode,
    );
    const temporaryStats = fstatSync(descriptor);
    if (!temporaryStats.isFile()) {
      throw new Error("Artifact temporary target must be a regular file.");
    }
    assertCurrentOwner("Artifact temporary target", temporaryStats);
    fchmodSync(descriptor, mode);
    writeFileSync(descriptor, contents, { encoding: "utf8" });
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temporaryPath, targetPath);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    if (lstatIfPresent(temporaryPath)) unlinkSync(temporaryPath);
  }
}

export function consumeJudgment({
  definition,
  input,
  inputDigest,
  surfaces,
  judgmentsByCapability,
}) {
  const record = judgmentsByCapability.get(definition.id);
  if (!record) {
    throw new Error(`Missing structured Agent judgment for ${definition.id}.`);
  }
  if (
    typeof record.agent_id !== "string" ||
    record.agent_id.length === 0 ||
    record.tool_name !== "structured_parity_judgment" ||
    typeof record.rationale !== "string" ||
    record.rationale.length === 0 ||
    !(record.latency_ms > 0) ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/u.test(
      record.recorded_at,
    )
  ) {
    throw new Error(
      `Structured Agent judgment audit is incomplete for ${definition.id}.`,
    );
  }
  if (!isDeepStrictEqual(record.input, input)) {
    throw new Error(
      `Structured Agent judgment input drifted for ${definition.id}.`,
    );
  }
  if (record.input_digest !== inputDigest) {
    throw new Error(
      `Structured Agent judgment digest drifted for ${definition.id}.`,
    );
  }
  if (record.output?.verdict !== "accepted") {
    throw new Error(
      `Structured Agent judgment is unresolved for ${definition.id}.`,
    );
  }
  for (const surfaceName of [
    "web",
    "desktop_cloud",
    "desktop_local",
    "native_only",
  ]) {
    if (
      !isDeepStrictEqual(
        record.output[surfaceName],
        dispositionSummary(surfaces[surfaceName]),
      )
    ) {
      throw new Error(
        `Structured Agent judgment output drifted for ${definition.id}.${surfaceName}.`,
      );
    }
  }
  return {
    agent_id: record.agent_id,
    tool_name: record.tool_name,
    input,
    input_digest: inputDigest,
    output: record.output,
    rationale: record.rationale,
    latency_ms: record.latency_ms,
    recorded_at: record.recorded_at,
  };
}
