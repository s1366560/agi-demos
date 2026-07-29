import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, posix, relative, resolve, win32 } from "node:path";

const DECLARATION_PREFIXES = ["planned:", "not_applicable:"];
const EXPECTED_INTEGRITY = Object.freeze({
  hash_algorithm: "sha256",
  verification_scope: "source_content_integrity_only",
  execution_evidence: false,
});

export function validateProductionEntryIntegrity(integrity) {
  if (
    integrity?.hash_algorithm !== EXPECTED_INTEGRITY.hash_algorithm ||
    integrity?.verification_scope !== EXPECTED_INTEGRITY.verification_scope ||
    integrity?.execution_evidence !== EXPECTED_INTEGRITY.execution_evidence ||
    Object.keys(integrity).length !== Object.keys(EXPECTED_INTEGRITY).length
  ) {
    throw new Error(
      "production_entry_integrity must declare SHA-256 source-content binding " +
        "without claiming execution evidence.",
    );
  }
  return { ...EXPECTED_INTEGRITY };
}

export function bindProductionEntrySurfaces(
  entriesBySurface,
  { repositoryRoot, definitionSourcePath, integrity },
) {
  const validatedIntegrity = validateProductionEntryIntegrity(integrity);
  return Object.fromEntries(
    ["desktop_cloud", "desktop_local", "native_only"].map((surfaceName) => [
      surfaceName,
      entriesBySurface[surfaceName].map((entry) =>
        bindProductionEntry(entry, {
          repositoryRoot,
          definitionSourcePath,
          integrity: validatedIntegrity,
        }),
      ),
    ]),
  );
}

function bindProductionEntry(
  declaredEntry,
  { repositoryRoot, definitionSourcePath, integrity },
) {
  if (typeof declaredEntry !== "string" || declaredEntry.length === 0) {
    throw new Error("Desktop production entries must be non-empty strings.");
  }
  const declaration = DECLARATION_PREFIXES.some((prefix) =>
    declaredEntry.startsWith(prefix),
  )
    ? declaredEntry
    : null;
  const sourcePath = declaration === null ? declaredEntry : definitionSourcePath;
  const absolutePath = resolveProductionEntryPath(repositoryRoot, sourcePath);
  return {
    entry_type: declaration === null ? "source" : "declaration",
    path: sourcePath,
    sha256: `sha256:${createHash(integrity.hash_algorithm)
      .update(readFileSync(absolutePath))
      .digest("hex")}`,
    declaration,
  };
}

function resolveProductionEntryPath(repositoryRoot, sourcePath) {
  if (
    typeof sourcePath !== "string" ||
    sourcePath.length === 0 ||
    sourcePath.includes("\\") ||
    posix.isAbsolute(sourcePath) ||
    win32.isAbsolute(sourcePath) ||
    isAbsolute(sourcePath)
  ) {
    throw new Error(
      `Production entry ${String(sourcePath)} must be repository-relative.`,
    );
  }

  const canonicalRepositoryRoot = realpathSync(repositoryRoot);
  const absolutePath = resolve(canonicalRepositoryRoot, ...sourcePath.split("/"));
  assertInsideRepository(canonicalRepositoryRoot, absolutePath, sourcePath);
  if (sourcePath.split("/").includes("..")) {
    throw new Error(
      `Production entry ${sourcePath} must not contain path traversal.`,
    );
  }
  if (posix.normalize(sourcePath) !== sourcePath || sourcePath === ".") {
    throw new Error(
      `Production entry ${sourcePath} must use a canonical repository-relative path.`,
    );
  }

  const stats = lstatSync(absolutePath);
  if (stats.isSymbolicLink()) {
    throw new Error(`Production entry ${sourcePath} must not be a symlink.`);
  }
  if (!stats.isFile()) {
    throw new Error(`Production entry ${sourcePath} must be a regular file.`);
  }

  const realPath = realpathSync(absolutePath);
  assertInsideRepository(canonicalRepositoryRoot, realPath, sourcePath);
  if (realPath !== absolutePath) {
    throw new Error(
      `Production entry ${sourcePath} must not traverse a symlink.`,
    );
  }
  return absolutePath;
}

function assertInsideRepository(repositoryRoot, candidatePath, sourcePath) {
  const repositoryRelativePath = relative(repositoryRoot, candidatePath);
  if (
    repositoryRelativePath === ".." ||
    repositoryRelativePath.split(/[\\/]/u)[0] === ".." ||
    isAbsolute(repositoryRelativePath)
  ) {
    throw new Error(
      `Production entry ${sourcePath} must stay inside the repository.`,
    );
  }
}
