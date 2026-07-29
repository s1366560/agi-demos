import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  appendFileSync,
  copyFileSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync, spawnSync } from "node:child_process";
import { test } from "node:test";

import { bindProductionEntrySurfaces } from "../contracts/desktop-web-parity/production-entry-integrity.mjs";

const repositoryRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const contractRoot = fileURLToPath(
  new URL("../contracts/desktop-web-parity/", import.meta.url),
);
const fragmentRegistry = readJson(
  join(contractRoot, "parity-capability-fragments.v2.json"),
);
const declaredProductionSourcePaths = collectDeclaredProductionSourcePaths();
const sha256Pattern = /^sha256:[0-9a-f]{64}$/u;
const productionEntryIntegrity = Object.freeze({
  hash_algorithm: "sha256",
  verification_scope: "source_content_integrity_only",
  execution_evidence: false,
});
const revisionFixturePaths = Object.freeze({
  definition: "contracts/capability-fragment.json",
  manifest: "contracts/parity-manifest.v2.json",
  source: "src/production-entry.ts",
});

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function runGit(repository, args, options = {}) {
  return execFileSync("git", args, {
    cwd: repository,
    encoding: "utf8",
    ...options,
  }).trim();
}

function commitAll(repository, subject) {
  runGit(repository, ["add", "."]);
  runGit(repository, ["commit", "-qm", subject]);
  return runGit(repository, ["rev-parse", "HEAD"]);
}

function createRevisionBindingFixture(t) {
  const fixtureRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-revision-binding-"),
  );
  mkdirSync(join(fixtureRoot, "contracts"), { recursive: true });
  mkdirSync(join(fixtureRoot, "src"), { recursive: true });
  writeFileSync(
    join(fixtureRoot, revisionFixturePaths.source),
    "export const audited = true;\n",
  );
  writeFileSync(
    join(fixtureRoot, revisionFixturePaths.definition),
    '{"capability":"planned"}\n',
  );
  writeFileSync(
    join(fixtureRoot, revisionFixturePaths.manifest),
    '{"schema_version":"2.0.0"}\n',
  );
  runGit(fixtureRoot, ["init", "-q"]);
  runGit(fixtureRoot, [
    "config",
    "user.email",
    "desktop-parity@example.invalid",
  ]);
  runGit(fixtureRoot, ["config", "user.name", "Desktop Parity Test"]);
  runGit(fixtureRoot, ["config", "core.autocrlf", "false"]);
  const auditRevision = commitAll(fixtureRoot, "test: add audited sources");
  const primaryBranch = runGit(fixtureRoot, [
    "rev-parse",
    "--abbrev-ref",
    "HEAD",
  ]);
  writeFileSync(
    join(fixtureRoot, "contracts/commit-b-only.txt"),
    "contract only\n",
  );
  const headRevision = commitAll(fixtureRoot, "test: add contract-only head");

  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  return {
    auditRevision,
    fixtureRoot,
    headRevision,
    primaryBranch,
  };
}

function bindFixtureEntries(
  fixture,
  {
    definitionSourcePath = revisionFixturePaths.definition,
    entries = [revisionFixturePaths.source],
    forbiddenSourcePaths = [],
    sourceRevision = fixture.auditRevision,
  } = {},
) {
  return bindProductionEntrySurfaces(
    {
      desktop_cloud: entries,
      desktop_local: entries,
      native_only: entries,
    },
    {
      repositoryRoot: fixture.fixtureRoot,
      definitionSourcePath,
      forbiddenSourcePaths,
      sourceRevision,
      integrity: productionEntryIntegrity,
    },
  );
}

function collectDeclaredProductionSourcePaths() {
  const paths = new Set();
  for (const fragmentName of fragmentRegistry.fragments) {
    const fragment = readJson(join(contractRoot, fragmentName));
    for (const capability of fragment.capabilities) {
      for (const field of [
        "cloud_entries",
        "local_entries",
        "native_entries",
      ]) {
        for (const entry of capability[field] ?? []) {
          if (
            !entry.startsWith("planned:") &&
            !entry.startsWith("not_applicable:")
          ) {
            paths.add(entry);
          }
        }
      }
    }
  }
  return [...paths].sort();
}

function createGeneratorFixture(t) {
  const fixtureRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-production-entry-"),
  );
  const externalRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-production-entry-output-"),
  );
  const fixtureContractRoot = join(
    fixtureRoot,
    "agi-stack/apps/desktop/contracts/desktop-web-parity",
  );
  cpSync(contractRoot, fixtureContractRoot, { recursive: true });
  for (const sourcePath of declaredProductionSourcePaths) {
    const target = join(fixtureRoot, sourcePath);
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(join(repositoryRoot, sourcePath), target);
  }
  runGit(fixtureRoot, ["init", "-q"]);
  runGit(fixtureRoot, [
    "config",
    "user.email",
    "desktop-parity@example.invalid",
  ]);
  runGit(fixtureRoot, ["config", "user.name", "Desktop Parity Test"]);
  runGit(fixtureRoot, ["config", "core.autocrlf", "false"]);
  const auditRevision = commitAll(
    fixtureRoot,
    "test: add audited generator fixture",
  );
  const metadataPath = join(
    fixtureContractRoot,
    "parity-capability-definitions.metadata.v2.json",
  );
  const metadata = readJson(metadataPath);
  for (const field of ["audit_revision", "web_revision", "desktop_revision"]) {
    metadata.references[field] = auditRevision;
  }
  writeFileSync(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`);
  const inventoryPath = join(
    fixtureContractRoot,
    "web-route-inventory.v2.json",
  );
  const inventory = readJson(inventoryPath);
  inventory.source_revision = auditRevision;
  writeFileSync(inventoryPath, `${JSON.stringify(inventory, null, 2)}\n`);
  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  t.after(() => rmSync(externalRoot, { recursive: true, force: true }));
  return {
    auditRevision,
    emitInputsPath: join(externalRoot, "review-inputs.jsonl"),
    fixtureRoot,
    fixtureContractRoot,
    generatorPath: join(fixtureContractRoot, "generate-parity-manifest-v2.mjs"),
  };
}

function runGeneratorCheck(fixture) {
  return spawnSync(
    process.execPath,
    [fixture.generatorPath, "--emit-inputs", fixture.emitInputsPath],
    {
      cwd: fixture.fixtureRoot,
      encoding: "utf8",
    },
  );
}

function assertCheckRejected(result, expectedPattern) {
  assert.notEqual(result.status, 0, result.stdout);
  assert.match(`${result.stderr}\n${result.stdout}`, expectedPattern);
}

test("Desktop production entries bind repository paths and source-only SHA-256 metadata", () => {
  const manifest = readJson(join(contractRoot, "parity-manifest.v2.json"));
  const metadata = readJson(
    join(contractRoot, "parity-capability-definitions.metadata.v2.json"),
  );
  const schema = readJson(join(contractRoot, "parity-manifest.v2.schema.json"));

  assert.deepEqual(
    manifest.production_entry_integrity,
    metadata.production_entry_integrity,
  );
  assert.deepEqual(manifest.production_entry_integrity, {
    hash_algorithm: "sha256",
    verification_scope: "source_content_integrity_only",
    execution_evidence: false,
  });
  assert.equal(
    manifest.source_inventories.web_routes.source_revision,
    manifest.references.web_revision,
  );
  assert.equal(
    manifest.source_inventories.web_routes.source_revision,
    manifest.references.audit_revision,
  );
  assert.deepEqual(
    schema.$defs.productionEntries.properties.desktop_cloud.items,
    { $ref: "#/$defs/productionEntry" },
  );

  for (const capability of manifest.capabilities) {
    for (const surfaceName of [
      "desktop_cloud",
      "desktop_local",
      "native_only",
    ]) {
      const entries = capability.production_entries[surfaceName];
      assert.equal(entries.length > 0, true, `${capability.id}.${surfaceName}`);
      assert.deepEqual(
        capability.judgment.input.production_entries[surfaceName],
        entries,
        `${capability.id}.${surfaceName}`,
      );
      assert.equal(
        capability.judgment.input.source_inventory_revisions.web_routes,
        manifest.references.web_revision,
        capability.id,
      );
      for (const entry of entries) {
        assert.deepEqual(
          Object.keys(entry).sort(),
          ["declaration", "entry_type", "path", "sha256"],
          `${capability.id}.${surfaceName}`,
        );
        assert.equal(entry.path.startsWith("/"), false, entry.path);
        assert.equal(entry.path.includes("\\"), false, entry.path);
        assert.equal(entry.path.split("/").includes(".."), false, entry.path);
        assert.match(entry.sha256, sha256Pattern, entry.path);
        assert.equal(
          entry.sha256,
          `sha256:${createHash("sha256")
            .update(
              execFileSync(
                "git",
                ["show", `${metadata.references.audit_revision}:${entry.path}`],
                { cwd: repositoryRoot },
              ),
            )
            .digest("hex")}`,
          entry.path,
        );
        assert.notEqual(
          entry.path,
          "agi-stack/apps/desktop/contracts/desktop-web-parity/" +
            "parity-manifest.v2.json",
          `${capability.id}.${surfaceName} must not bind the manifest to itself`,
        );
        assert.equal(
          ["source", "declaration"].includes(entry.entry_type),
          true,
          entry.path,
        );
        if (entry.entry_type === "source") {
          assert.equal(entry.declaration, null, entry.path);
        } else {
          assert.match(entry.declaration, /^(planned|not_applicable):/u);
        }
      }
    }

    const expectedDigest = `sha256:${createHash("sha256")
      .update(JSON.stringify(capability.judgment.input))
      .digest("hex")}`;
    assert.equal(
      capability.judgment.input_digest,
      expectedDigest,
      capability.id,
    );
  }
});

test("changing any declared Desktop production source invalidates manifest check", (t) => {
  const fixture = createGeneratorFixture(t);
  const baseline = runGeneratorCheck(fixture);
  assert.equal(baseline.status, 0, baseline.stderr);

  const requiredBoundaryPaths = [
    "agi-stack/apps/desktop/electron/main/index.ts",
    "agi-stack/apps/desktop/electron/preload/index.ts",
    "agi-stack/apps/desktop/src/App.tsx",
    "agi-stack/apps/desktop/sidecar/src/application_vault.rs",
    ".github/workflows/desktop-release.yml",
    "agi-stack/apps/desktop/src/features/settings/ManagedResourceViews.tsx",
  ];
  for (const sourcePath of requiredBoundaryPaths) {
    assert.equal(
      declaredProductionSourcePaths.includes(sourcePath),
      true,
      `${sourcePath} must be declared by a capability`,
    );
  }

  for (const sourcePath of declaredProductionSourcePaths) {
    const absolutePath = join(fixture.fixtureRoot, sourcePath);
    const original = readFileSync(absolutePath);
    appendFileSync(absolutePath, "\nproduction-entry-integrity-mutation\n");
    assert.throws(
      () =>
        bindProductionEntrySurfaces(
          {
            desktop_cloud: [sourcePath],
            desktop_local: [sourcePath],
            native_only: [sourcePath],
          },
          {
            repositoryRoot: fixture.fixtureRoot,
            definitionSourcePath:
              "agi-stack/apps/desktop/contracts/desktop-web-parity/" +
              fragmentRegistry.fragments[0],
            sourceRevision: fixture.auditRevision,
            integrity: productionEntryIntegrity,
          },
        ),
      /current HEAD blob differs from live regular-file bytes/iu,
      sourcePath,
    );
    writeFileSync(absolutePath, original);
  }
});

test("production entry binding rejects traversal, absolute paths, and non-files", (t) => {
  const fixture = createRevisionBindingFixture(t);
  const invalidEntries = [
    {
      name: "traversal",
      entry: "src/../src/production-entry.ts",
      expected: /must not contain path traversal/iu,
    },
    {
      name: "repository escape",
      entry: "../outside-production-entry.ts",
      expected: /must stay inside the repository/iu,
    },
    {
      name: "absolute path",
      entry: join(tmpdir(), "outside-production-entry.ts"),
      expected: /must be repository-relative/iu,
    },
    {
      name: "directory",
      entry: "src",
      expected: /must be a regular file/iu,
    },
    {
      name: "backslash",
      entry: "src\\production-entry.ts",
      expected: /must be repository-relative/iu,
    },
    {
      name: "dot segment",
      entry: "./src/production-entry.ts",
      expected: /canonical repository-relative path/iu,
    },
    {
      name: "duplicate separator",
      entry: "src//production-entry.ts",
      expected: /canonical repository-relative path/iu,
    },
  ];

  for (const invalid of invalidEntries) {
    assert.throws(
      () => bindFixtureEntries(fixture, { entries: [invalid.entry] }),
      invalid.expected,
      invalid.name,
    );
  }
});

test("production entry binding rejects direct symlinks and realpath escape", (t) => {
  const directFixture = createRevisionBindingFixture(t);
  const directEntry = join(
    directFixture.fixtureRoot,
    revisionFixturePaths.source,
  );
  const externalRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-production-entry-external-"),
  );
  const externalFile = join(externalRoot, "App.tsx");
  writeFileSync(externalFile, "export const outside = true;\n");
  t.after(() => rmSync(externalRoot, { recursive: true, force: true }));

  unlinkSync(directEntry);
  try {
    symlinkSync(externalFile, directEntry);
  } catch (error) {
    if (error?.code === "EPERM") {
      t.skip("The current platform does not permit test symlink creation.");
      return;
    }
    throw error;
  }
  assert.throws(
    () => bindFixtureEntries(directFixture),
    /must not be a symlink/iu,
  );

  const parentFixture = createRevisionBindingFixture(t);
  const linkedDirectory = join(parentFixture.fixtureRoot, "linked-source");
  symlinkSync(externalRoot, linkedDirectory, "dir");
  assert.throws(
    () =>
      bindFixtureEntries(parentFixture, {
        entries: ["linked-source/App.tsx"],
      }),
    /must stay inside the repository/iu,
  );
});

test("production entries bind audited revision, current HEAD, and live bytes", (t) => {
  const fixture = createRevisionBindingFixture(t);
  const expectedSha256 = `sha256:${createHash("sha256")
    .update(
      execFileSync(
        "git",
        ["show", `${fixture.auditRevision}:${revisionFixturePaths.source}`],
        { cwd: fixture.fixtureRoot },
      ),
    )
    .digest("hex")}`;

  const bound = bindFixtureEntries(fixture);
  assert.equal(bound.desktop_cloud[0].sha256, expectedSha256);
  assert.equal(fixture.auditRevision.length, 40);
  assert.notEqual(fixture.auditRevision, fixture.headRevision);
});

test("declarations bind their audited definition fragment without manifest self-reference", (t) => {
  const fixture = createRevisionBindingFixture(t);
  const [declaration] = bindFixtureEntries(fixture, {
    entries: ["planned:contracts/parity-manifest.v2.json"],
  }).desktop_cloud;
  const expectedSha256 = `sha256:${createHash("sha256")
    .update(
      execFileSync(
        "git",
        ["show", `${fixture.auditRevision}:${revisionFixturePaths.definition}`],
        { cwd: fixture.fixtureRoot },
      ),
    )
    .digest("hex")}`;

  assert.equal(declaration.entry_type, "declaration");
  assert.equal(declaration.path, revisionFixturePaths.definition);
  assert.notEqual(declaration.path, revisionFixturePaths.manifest);
  assert.equal(declaration.sha256, expectedSha256);
});

test("production entries reject a direct manifest self-reference", (t) => {
  const fixture = createRevisionBindingFixture(t);

  assert.throws(
    () =>
      bindFixtureEntries(fixture, {
        entries: [revisionFixturePaths.manifest],
        forbiddenSourcePaths: [revisionFixturePaths.manifest],
      }),
    /must not bind the parity manifest to itself/iu,
  );
});

test("production entry revisions reject missing, abbreviated, branch, and tag names", (t) => {
  const fixture = createRevisionBindingFixture(t);
  runGit(fixture.fixtureRoot, [
    "branch",
    "audited-revision",
    fixture.auditRevision,
  ]);
  runGit(fixture.fixtureRoot, [
    "tag",
    "audited-revision-tag",
    fixture.auditRevision,
  ]);
  runGit(fixture.fixtureRoot, [
    "tag",
    "-a",
    "audited-annotated-tag",
    "-m",
    "annotated audit tag",
    fixture.auditRevision,
  ]);
  const annotatedTagObject = runGit(fixture.fixtureRoot, [
    "rev-parse",
    "audited-annotated-tag^{tag}",
  ]);

  const invalidRevisions = [
    "f".repeat(40),
    fixture.auditRevision.slice(0, 12),
    "audited-revision",
    "audited-revision-tag",
    annotatedTagObject,
  ];
  for (const sourceRevision of invalidRevisions) {
    assert.throws(
      () => bindFixtureEntries(fixture, { sourceRevision }),
      /source revision.*full.*commit|does not resolve|identify a commit directly/iu,
      sourceRevision,
    );
  }
});

test("production entry revisions reject a commit outside current HEAD ancestry", (t) => {
  const fixture = createRevisionBindingFixture(t);
  runGit(fixture.fixtureRoot, [
    "switch",
    "-q",
    "-c",
    "sibling-audit",
    fixture.auditRevision,
  ]);
  writeFileSync(
    join(fixture.fixtureRoot, "contracts/sibling-only.txt"),
    "sibling\n",
  );
  const siblingRevision = commitAll(
    fixture.fixtureRoot,
    "test: add sibling contract",
  );
  runGit(fixture.fixtureRoot, ["switch", "-q", fixture.primaryBranch]);

  assert.throws(
    () => bindFixtureEntries(fixture, { sourceRevision: siblingRevision }),
    /must be an ancestor of current HEAD/iu,
  );
});

test("production entry binding rejects audited, HEAD, and live byte drift", (t) => {
  const auditedDrift = createRevisionBindingFixture(t);
  writeFileSync(
    join(auditedDrift.fixtureRoot, revisionFixturePaths.source),
    "export const audited = false;\n",
  );
  commitAll(auditedDrift.fixtureRoot, "test: change production source");
  assert.throws(
    () => bindFixtureEntries(auditedDrift),
    /audited revision.*current HEAD|current HEAD.*audited revision/iu,
  );

  const liveDrift = createRevisionBindingFixture(t);
  writeFileSync(
    join(liveDrift.fixtureRoot, revisionFixturePaths.source),
    "export const dirty = true;\n",
  );
  assert.throws(
    () => bindFixtureEntries(liveDrift),
    /current HEAD.*live.*bytes|live.*current HEAD.*bytes/iu,
  );

  const missingAtAudit = createRevisionBindingFixture(t);
  const laterPath = "src/created-after-audit.ts";
  writeFileSync(
    join(missingAtAudit.fixtureRoot, laterPath),
    "export const later = true;\n",
  );
  commitAll(missingAtAudit.fixtureRoot, "test: add post-audit source");
  assert.throws(
    () => bindFixtureEntries(missingAtAudit, { entries: [laterPath] }),
    /does not exist.*audited revision|audited revision.*does not exist/iu,
  );
});

test("declaration fragments may not drift after the audited revision", (t) => {
  const fixture = createRevisionBindingFixture(t);
  writeFileSync(
    join(fixture.fixtureRoot, revisionFixturePaths.definition),
    '{"capability":"changed"}\n',
  );
  commitAll(fixture.fixtureRoot, "test: change capability fragment");

  assert.throws(
    () =>
      bindFixtureEntries(fixture, {
        entries: ["planned:src/future-route.tsx"],
      }),
    /audited revision.*current HEAD|current HEAD.*audited revision/iu,
  );
});

test("production entries reject symlink blobs at the audited revision or HEAD", (t) => {
  const auditedSymlinkRoot = mkdtempSync(
    join(tmpdir(), "desktop-parity-audited-symlink-"),
  );
  t.after(() => rmSync(auditedSymlinkRoot, { recursive: true, force: true }));
  mkdirSync(join(auditedSymlinkRoot, "contracts"), { recursive: true });
  mkdirSync(join(auditedSymlinkRoot, "src"), { recursive: true });
  writeFileSync(
    join(auditedSymlinkRoot, "src/target.ts"),
    "export const audited = true;\n",
  );
  writeFileSync(
    join(auditedSymlinkRoot, revisionFixturePaths.definition),
    '{"capability":"planned"}\n',
  );
  symlinkSync(
    "target.ts",
    join(auditedSymlinkRoot, revisionFixturePaths.source),
  );
  runGit(auditedSymlinkRoot, ["init", "-q"]);
  runGit(auditedSymlinkRoot, [
    "config",
    "user.email",
    "desktop-parity@example.invalid",
  ]);
  runGit(auditedSymlinkRoot, ["config", "user.name", "Desktop Parity Test"]);
  const auditedSymlinkRevision = commitAll(
    auditedSymlinkRoot,
    "test: add audited symlink",
  );
  unlinkSync(join(auditedSymlinkRoot, revisionFixturePaths.source));
  copyFileSync(
    join(auditedSymlinkRoot, "src/target.ts"),
    join(auditedSymlinkRoot, revisionFixturePaths.source),
  );
  commitAll(auditedSymlinkRoot, "test: replace audited symlink");
  assert.throws(
    () =>
      bindFixtureEntries({
        auditRevision: auditedSymlinkRevision,
        fixtureRoot: auditedSymlinkRoot,
      }),
    /must be a 100644 or 100755 regular Git blob at audited revision/iu,
  );

  const headSymlink = createRevisionBindingFixture(t);
  writeFileSync(
    join(headSymlink.fixtureRoot, "src/target.ts"),
    "export const audited = true;\n",
  );
  unlinkSync(join(headSymlink.fixtureRoot, revisionFixturePaths.source));
  symlinkSync(
    "target.ts",
    join(headSymlink.fixtureRoot, revisionFixturePaths.source),
  );
  commitAll(headSymlink.fixtureRoot, "test: add HEAD symlink");
  unlinkSync(join(headSymlink.fixtureRoot, revisionFixturePaths.source));
  copyFileSync(
    join(headSymlink.fixtureRoot, "src/target.ts"),
    join(headSymlink.fixtureRoot, revisionFixturePaths.source),
  );
  assert.throws(
    () => bindFixtureEntries(headSymlink),
    /must be a 100644 or 100755 regular Git blob at current HEAD/iu,
  );
});
