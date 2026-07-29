import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, posix, relative, resolve, win32 } from "node:path";

const DECLARATION_PREFIXES = ["planned:", "not_applicable:"];
const GIT_REVISION_PATTERN = /^[0-9a-f]{40}$/u;
const GIT_REGULAR_FILE_MODES = new Set(["100644", "100755"]);
const MAX_GIT_BLOB_BYTES = 32 * 1024 * 1024;
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
  {
    repositoryRoot,
    definitionSourcePath,
    forbiddenSourcePaths = [],
    sourceRevision,
    integrity,
  },
) {
  const validatedIntegrity = validateProductionEntryIntegrity(integrity);
  const revisionBinding = resolveRevisionBinding(
    repositoryRoot,
    sourceRevision,
  );
  const forbiddenSourcePathSet = new Set(forbiddenSourcePaths);
  const sourceBytesByPath = new Map();
  return Object.fromEntries(
    ["desktop_cloud", "desktop_local", "native_only"].map((surfaceName) => [
      surfaceName,
      entriesBySurface[surfaceName].map((entry) =>
        bindProductionEntry(entry, {
          repositoryRoot,
          definitionSourcePath,
          forbiddenSourcePathSet,
          revisionBinding,
          sourceBytesByPath,
          integrity: validatedIntegrity,
        }),
      ),
    ]),
  );
}

function bindProductionEntry(
  declaredEntry,
  {
    repositoryRoot,
    definitionSourcePath,
    forbiddenSourcePathSet,
    revisionBinding,
    sourceBytesByPath,
    integrity,
  },
) {
  if (typeof declaredEntry !== "string" || declaredEntry.length === 0) {
    throw new Error("Desktop production entries must be non-empty strings.");
  }
  const declaration = DECLARATION_PREFIXES.some((prefix) =>
    declaredEntry.startsWith(prefix),
  )
    ? declaredEntry
    : null;
  const sourcePath =
    declaration === null ? declaredEntry : definitionSourcePath;
  if (forbiddenSourcePathSet.has(sourcePath)) {
    throw new Error(
      `Production entry ${sourcePath} must not bind the parity manifest to itself.`,
    );
  }
  let sourceBytes = sourceBytesByPath.get(sourcePath);
  if (!sourceBytes) {
    sourceBytes = readRevisionBoundProductionEntry({
      repositoryRoot,
      revisionBinding,
      sourcePath,
    });
    sourceBytesByPath.set(sourcePath, sourceBytes);
  }
  return {
    entry_type: declaration === null ? "source" : "declaration",
    path: sourcePath,
    sha256: `sha256:${createHash(integrity.hash_algorithm)
      .update(sourceBytes)
      .digest("hex")}`,
    declaration,
  };
}

function resolveRevisionBinding(repositoryRoot, sourceRevision) {
  if (
    typeof sourceRevision !== "string" ||
    !GIT_REVISION_PATTERN.test(sourceRevision)
  ) {
    throw new Error(
      "Production entry source revision must be a full 40-character Git commit.",
    );
  }
  const canonicalRepositoryRoot = realpathSync(repositoryRoot);
  const auditedRevision = resolveGitCommit(
    canonicalRepositoryRoot,
    sourceRevision,
    "Production entry source revision",
  );
  if (auditedRevision !== sourceRevision) {
    throw new Error(
      "Production entry source revision must identify a commit directly.",
    );
  }
  const headRevision = resolveGitCommit(
    canonicalRepositoryRoot,
    "HEAD",
    "Current HEAD",
  );
  try {
    execFileSync(
      "git",
      ["merge-base", "--is-ancestor", auditedRevision, headRevision],
      {
        cwd: canonicalRepositoryRoot,
        stdio: "pipe",
      },
    );
  } catch {
    throw new Error(
      `Production entry source revision ${auditedRevision} must be an ancestor ` +
        `of current HEAD ${headRevision}.`,
    );
  }
  return {
    auditedRevision,
    headRevision,
  };
}

function resolveGitCommit(repositoryRoot, revision, label) {
  try {
    const resolvedRevision = execFileSync(
      "git",
      ["rev-parse", "--verify", `${revision}^{commit}`],
      {
        cwd: repositoryRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    ).trim();
    if (!GIT_REVISION_PATTERN.test(resolvedRevision)) {
      throw new Error("resolved revision is not a full commit");
    }
    return resolvedRevision;
  } catch {
    throw new Error(`${label} ${revision} does not resolve to a Git commit.`);
  }
}

function readRevisionBoundProductionEntry({
  repositoryRoot,
  revisionBinding,
  sourcePath,
}) {
  const absolutePath = resolveProductionEntryPath(repositoryRoot, sourcePath);
  const liveBytes = readFileSync(absolutePath);
  const auditedBytes = readGitRegularFile(
    repositoryRoot,
    revisionBinding.auditedRevision,
    sourcePath,
    "audited revision",
  );
  const headBytes = readGitRegularFile(
    repositoryRoot,
    revisionBinding.headRevision,
    sourcePath,
    "current HEAD",
  );
  if (!auditedBytes.equals(headBytes)) {
    throw new Error(
      `Production entry ${sourcePath} differs between audited revision ` +
        `${revisionBinding.auditedRevision} and current HEAD ` +
        `${revisionBinding.headRevision}.`,
    );
  }
  if (!headBytes.equals(liveBytes)) {
    throw new Error(
      `Production entry ${sourcePath} current HEAD blob differs from live ` +
        "regular-file bytes.",
    );
  }
  return auditedBytes;
}

function readGitRegularFile(
  repositoryRoot,
  revision,
  sourcePath,
  revisionLabel,
) {
  let treeOutput;
  try {
    treeOutput = execFileSync(
      "git",
      [
        "--literal-pathspecs",
        "ls-tree",
        "-z",
        "--full-tree",
        revision,
        "--",
        sourcePath,
      ],
      {
        cwd: repositoryRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
  } catch {
    throw new Error(
      `Production entry ${sourcePath} cannot be inspected at ${revisionLabel} ` +
        `${revision}.`,
    );
  }
  const records = treeOutput.split("\0").filter((record) => record.length > 0);
  if (records.length !== 1) {
    throw new Error(
      `Production entry ${sourcePath} does not exist as one file at ` +
        `${revisionLabel} ${revision}.`,
    );
  }
  const separatorIndex = records[0].indexOf("\t");
  const metadata = records[0].slice(0, separatorIndex).split(" ");
  const resolvedPath = records[0].slice(separatorIndex + 1);
  const [mode, objectType] = metadata;
  if (
    separatorIndex < 0 ||
    resolvedPath !== sourcePath ||
    objectType !== "blob" ||
    !GIT_REGULAR_FILE_MODES.has(mode)
  ) {
    throw new Error(
      `Production entry ${sourcePath} must be a 100644 or 100755 regular Git ` +
        `blob at ${revisionLabel} ${revision}.`,
    );
  }
  try {
    return execFileSync("git", ["show", `${revision}:${sourcePath}`], {
      cwd: repositoryRoot,
      encoding: "buffer",
      maxBuffer: MAX_GIT_BLOB_BYTES,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    throw new Error(
      `Production entry ${sourcePath} cannot be read at ${revisionLabel} ` +
        `${revision}.`,
    );
  }
}

function resolveProductionEntryPath(repositoryRoot, sourcePath) {
  if (
    typeof sourcePath !== "string" ||
    sourcePath.length === 0 ||
    /[\u0000-\u001f\u007f]/u.test(sourcePath) ||
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
  const absolutePath = resolve(
    canonicalRepositoryRoot,
    ...sourcePath.split("/"),
  );
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
