import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import {
  dirname,
  isAbsolute,
  posix,
  relative,
  resolve,
  sep,
  win32,
} from "node:path";
import { isDeepStrictEqual } from "node:util";

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

function pathEscapesRoot(root, candidate) {
  const relativePath = relative(root, candidate);
  return (
    relativePath === ".." ||
    relativePath.startsWith(`..${sep}`) ||
    isAbsolute(relativePath)
  );
}

export function canonicalRepositoryRelativePath(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    isAbsolute(value) ||
    posix.isAbsolute(value) ||
    win32.isAbsolute(value) ||
    value.includes("\\")
  ) {
    return null;
  }
  const segments = value.split("/");
  if (
    segments.some(
      (segment) => segment.length === 0 || segment === "." || segment === "..",
    )
  ) {
    return null;
  }
  const normalized = posix.normalize(value);
  return normalized === value ? normalized : null;
}

export function validateArtifactFiles(
  errors,
  artifacts,
  evidenceRunPath,
  startedAt,
  completedAt,
) {
  const resolvedArtifactsById = new Map();
  if (typeof evidenceRunPath !== "string" || evidenceRunPath.length === 0) {
    errors.push("commit-bound artifact validation requires evidenceRunPath");
    return resolvedArtifactsById;
  }

  let resolvedEvidenceRoot;
  try {
    resolvedEvidenceRoot = realpathSync(dirname(resolve(evidenceRunPath)));
    if (!lstatSync(resolvedEvidenceRoot).isDirectory()) {
      errors.push("evidenceRunPath parent must reference a directory");
      return resolvedArtifactsById;
    }
  } catch {
    errors.push("evidenceRunPath parent must reference a readable directory");
    return resolvedArtifactsById;
  }

  for (const [index, artifact] of artifacts.entries()) {
    if (!isRecord(artifact)) continue;
    const artifactPath = `$.artifacts[${index}]`;
    const location = artifact.location;
    if (typeof location !== "string" || location.length === 0) continue;
    if (
      isAbsolute(location) ||
      posix.isAbsolute(location) ||
      win32.isAbsolute(location)
    ) {
      errors.push(`${artifactPath}.location must not be absolute`);
      continue;
    }
    if (location.split(/[\\/]/u).includes("..")) {
      errors.push(`${artifactPath}.location must not contain path traversal`);
      continue;
    }

    const candidate = resolve(resolvedEvidenceRoot, location);
    if (pathEscapesRoot(resolvedEvidenceRoot, candidate)) {
      errors.push(`${artifactPath}.location escapes evidenceRoot`);
      continue;
    }

    let artifactStats;
    let resolvedArtifact;
    try {
      artifactStats = lstatSync(candidate);
      resolvedArtifact = realpathSync(candidate);
    } catch {
      errors.push(`${artifactPath}.location is missing from evidenceRoot`);
      continue;
    }
    if (pathEscapesRoot(resolvedEvidenceRoot, resolvedArtifact)) {
      errors.push(
        `${artifactPath}.location escapes evidenceRoot through a symlink`,
      );
      continue;
    }
    if (!artifactStats.isFile()) {
      errors.push(`${artifactPath}.location must reference a regular file`);
      continue;
    }
    if (typeof artifact.artifact_id === "string") {
      resolvedArtifactsById.set(artifact.artifact_id, resolvedArtifact);
    }

    if (
      typeof artifact.sha256 === "string" &&
      digest(readFileSync(resolvedArtifact)) !== artifact.sha256
    ) {
      errors.push(`${artifactPath}.sha256 does not match artifact bytes`);
    }

    const producedAt = Date.parse(artifact.produced_at);
    if (!Number.isFinite(producedAt)) {
      errors.push(`${artifactPath}.produced_at must be a valid timestamp`);
    } else if (
      Number.isFinite(startedAt) &&
      Number.isFinite(completedAt) &&
      (producedAt < startedAt || producedAt > completedAt)
    ) {
      errors.push(
        `${artifactPath}.produced_at must fall within the run time window`,
      );
    }
  }
  return resolvedArtifactsById;
}

function validateSharedContractArtifact(
  errors,
  artifactsById,
  resolvedArtifactsById,
  artifactId,
  path,
) {
  const artifact = artifactsById.get(artifactId);
  if (!artifact) {
    errors.push(`${path} references an unknown artifact ${artifactId}`);
    return { artifact: null, bytes: null };
  }
  if (
    artifact.channel !== "shared" ||
    !Array.isArray(artifact.evidence_roles) ||
    !artifact.evidence_roles.includes("contract")
  ) {
    errors.push(`${path} must reference a shared contract artifact`);
  }
  const resolvedArtifact = resolvedArtifactsById.get(artifactId);
  if (!resolvedArtifact) {
    errors.push(`${path} points to a missing artifact file`);
    return { artifact, bytes: null };
  }
  return {
    artifact,
    bytes: readFileSync(resolvedArtifact),
  };
}

export function parseBoundJsonArtifact(errors, bytes, path) {
  if (!bytes) return null;
  try {
    return JSON.parse(bytes.toString("utf8"));
  } catch {
    errors.push(`${path} must reference valid JSON`);
    return null;
  }
}

export function validateBoundReferenceArtifacts(
  errors,
  schema,
  run,
  artifactsById,
  resolvedArtifactsById,
  suppliedManifest,
) {
  const schemaBinding = validateSharedContractArtifact(
    errors,
    artifactsById,
    resolvedArtifactsById,
    run.schema_artifact_id,
    "$.schema_artifact_id",
  );
  const expectedSchemaLocation =
    typeof run.$schema === "string"
      ? run.$schema.replace(/^\.\//u, "")
      : null;
  if (
    schemaBinding.artifact &&
    schemaBinding.artifact.location !== expectedSchemaLocation
  ) {
    errors.push(
      "$.schema_artifact_id location must resolve the run $schema reference",
    );
  }
  const packetSchema = parseBoundJsonArtifact(
    errors,
    schemaBinding.bytes,
    "$.schema_artifact_id",
  );
  if (packetSchema && !isDeepStrictEqual(packetSchema, schema)) {
    errors.push("$.schema_artifact_id does not match the validating schema");
  }

  const contractBinding = validateSharedContractArtifact(
    errors,
    artifactsById,
    resolvedArtifactsById,
    run.desired_contract?.artifact_id,
    "$.desired_contract.artifact_id",
  );
  if (
    contractBinding.artifact &&
    contractBinding.artifact.sha256 !== run.desired_contract?.sha256
  ) {
    errors.push(
      "$.desired_contract.artifact_id sha256 must equal $.desired_contract.sha256",
    );
  }
  if (
    contractBinding.bytes &&
    digest(contractBinding.bytes) !== run.desired_contract?.sha256
  ) {
    errors.push(
      "$.desired_contract.artifact_id sha256 does not match artifact bytes",
    );
  }
  const packetManifest = parseBoundJsonArtifact(
    errors,
    contractBinding.bytes,
    "$.desired_contract.artifact_id",
  );
  if (
    packetManifest &&
    suppliedManifest &&
    !isDeepStrictEqual(packetManifest, suppliedManifest)
  ) {
    errors.push(
      "$.desired_contract.artifact_id does not match the supplied manifest",
    );
  }
  return packetManifest ?? suppliedManifest;
}
