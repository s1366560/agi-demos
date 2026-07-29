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
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const repositoryRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const contractRoot = fileURLToPath(
  new URL("../contracts/desktop-web-parity/", import.meta.url),
);
const fragmentRegistry = readJson(
  join(contractRoot, "parity-capability-fragments.v2.json"),
);
const declaredProductionSourcePaths = collectDeclaredProductionSourcePaths();
const sha256Pattern = /^sha256:[0-9a-f]{64}$/u;

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function collectDeclaredProductionSourcePaths() {
  const paths = new Set();
  for (const fragmentName of fragmentRegistry.fragments) {
    const fragment = readJson(join(contractRoot, fragmentName));
    for (const capability of fragment.capabilities) {
      for (const field of ["cloud_entries", "local_entries", "native_entries"]) {
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
  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  return {
    fixtureRoot,
    fixtureContractRoot,
    generatorPath: join(
      fixtureContractRoot,
      "generate-parity-manifest-v2.mjs",
    ),
  };
}

function runGeneratorCheck(fixture) {
  return spawnSync(process.execPath, [fixture.generatorPath, "--check"], {
    cwd: fixture.fixtureRoot,
    encoding: "utf8",
  });
}

function replaceDeclaredEntry(fixture, originalEntry, replacementEntry) {
  for (const fragmentName of fragmentRegistry.fragments) {
    const fragmentPath = join(fixture.fixtureContractRoot, fragmentName);
    const fragment = readJson(fragmentPath);
    for (const capability of fragment.capabilities) {
      for (const field of ["cloud_entries", "local_entries", "native_entries"]) {
        const index = capability[field]?.indexOf(originalEntry) ?? -1;
        if (index === -1) continue;
        capability[field][index] = replacementEntry;
        writeFileSync(fragmentPath, `${JSON.stringify(fragment, null, 2)}\n`);
        return;
      }
    }
  }
  throw new Error(`No definition entry found for ${originalEntry}.`);
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
            .update(readFileSync(join(repositoryRoot, entry.path)))
            .digest("hex")}`,
          entry.path,
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
    assert.equal(capability.judgment.input_digest, expectedDigest, capability.id);
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
    const result = runGeneratorCheck(fixture);
    assertCheckRejected(
      result,
      /Structured Agent judgment (input|digest) drifted|manifest.*stale/iu,
    );
    writeFileSync(absolutePath, original);
  }
});

test("production entry binding rejects traversal, absolute paths, and non-files", (t) => {
  const originalEntry = "agi-stack/apps/desktop/src/App.tsx";
  const invalidEntries = [
    {
      name: "traversal",
      entry: "agi-stack/apps/desktop/src/../src/App.tsx",
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
      entry: "agi-stack/apps/desktop/src",
      expected: /must be a regular file/iu,
    },
  ];

  for (const invalid of invalidEntries) {
    const fixture = createGeneratorFixture(t);
    replaceDeclaredEntry(fixture, originalEntry, invalid.entry);
    const result = runGeneratorCheck(fixture);
    assertCheckRejected(result, invalid.expected);
  }
});

test("production entry binding rejects direct symlinks and realpath escape", (t) => {
  const directFixture = createGeneratorFixture(t);
  const directEntry = join(
    directFixture.fixtureRoot,
    "agi-stack/apps/desktop/src/App.tsx",
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
  assertCheckRejected(runGeneratorCheck(directFixture), /must not be a symlink/iu);

  const parentFixture = createGeneratorFixture(t);
  const linkedDirectory = join(parentFixture.fixtureRoot, "linked-source");
  symlinkSync(externalRoot, linkedDirectory, "dir");
  replaceDeclaredEntry(
    parentFixture,
    "agi-stack/apps/desktop/src/App.tsx",
    "linked-source/App.tsx",
  );
  assertCheckRejected(
    runGeneratorCheck(parentFixture),
    /must stay inside the repository/iu,
  );
});
