import assert from "node:assert/strict";
import {
  chmodSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { test } from "node:test";

import * as ledger from "../contracts/desktop-web-parity/parity-judgment-ledger.mjs";

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "desktop-parity-ledger-"));
  const repositoryRoot = join(root, "repository");
  const externalRoot = join(root, "external");
  mkdirSync(repositoryRoot);
  mkdirSync(externalRoot);
  const manifestPath = join(repositoryRoot, "parity-manifest.v2.json");
  writeFileSync(manifestPath, '{"capabilities":[]}\n');
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return { externalRoot, manifestPath, repositoryRoot };
}

function writeOwnerOnly(path, contents = "{}\n") {
  writeFileSync(path, contents, { mode: 0o600 });
  chmodSync(path, 0o600);
}

function auditedCapabilityIds() {
  const registryPath = new URL(
    "../contracts/desktop-web-parity/parity-capability-fragments.v2.json",
    import.meta.url,
  );
  const registry = JSON.parse(readFileSync(registryPath, "utf8"));
  return registry.fragments.flatMap((fileName) => {
    const definitionPath = new URL(
      `../contracts/desktop-web-parity/${fileName}`,
      import.meta.url,
    );
    return JSON.parse(readFileSync(definitionPath, "utf8")).capabilities.map(
      (capability) => capability.id,
    );
  });
}

test("judgment input rejects symlinks, non-files, and realpath repository escape", (t) => {
  const { externalRoot, manifestPath, repositoryRoot } = fixture(t);
  const judgmentPath = join(externalRoot, "judgments.jsonl");
  const judgmentLink = join(externalRoot, "judgments-link.jsonl");
  writeOwnerOnly(judgmentPath);
  symlinkSync(judgmentPath, judgmentLink);

  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(["--judgments", judgmentLink], {
        manifestPath,
        repositoryRoot,
      }),
    /symbolic link/u,
  );

  const directoryPath = join(externalRoot, "judgments-directory");
  mkdirSync(directoryPath, { mode: 0o700 });
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(["--judgments", directoryPath], {
        manifestPath,
        repositoryRoot,
      }),
    /regular file/u,
  );

  const repositoryJudgments = join(repositoryRoot, "judgments.jsonl");
  const repositoryLink = join(externalRoot, "repository-link");
  writeOwnerOnly(repositoryJudgments);
  symlinkSync(repositoryRoot, repositoryLink);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        ["--judgments", join(repositoryLink, "judgments.jsonl")],
        { manifestPath, repositoryRoot },
      ),
    /outside the repository/u,
  );

  const hardLinkedJudgments = join(externalRoot, "hard-linked-judgments.jsonl");
  linkSync(repositoryJudgments, hardLinkedJudgments);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        ["--judgments", hardLinkedJudgments],
        { manifestPath, repositoryRoot },
      ),
    /hard link/u,
  );
});

test("judgment read revalidates the protected file after option parsing", (t) => {
  const { externalRoot, manifestPath, repositoryRoot } = fixture(t);
  const judgmentPath = join(externalRoot, "judgments.jsonl");
  writeOwnerOnly(judgmentPath, '{"input":{"capability_id":"safe"}}\n');
  const options = ledger.parseManifestGeneratorOptions(
    ["--judgments", judgmentPath],
    { manifestPath, repositoryRoot },
  );
  assert.equal(options.outputPath, realpathSync(manifestPath));
  assert.equal(options.outputOwnerOnly, false);

  unlinkSync(judgmentPath);
  symlinkSync(manifestPath, judgmentPath);
  assert.throws(
    () =>
      ledger.loadJudgmentRecords(options, {
        manifestPath,
        repositoryRoot,
      }),
    /symbolic link|outside the repository/u,
  );
});

test("generator outputs reject repository aliases and unsafe existing targets", (t) => {
  const { externalRoot, manifestPath, repositoryRoot } = fixture(t);
  const judgmentPath = join(externalRoot, "judgments.jsonl");
  writeOwnerOnly(judgmentPath);

  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        [
          "--judgments",
          judgmentPath,
          "--output",
          join(repositoryRoot, "other.json"),
        ],
        { manifestPath, repositoryRoot },
      ),
    /exact manifest target/u,
  );

  const repositoryLink = join(externalRoot, "repository-link");
  symlinkSync(repositoryRoot, repositoryLink);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        ["--emit-inputs", join(repositoryLink, "inputs.jsonl")],
        { manifestPath, repositoryRoot },
      ),
    /outside the repository/u,
  );
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        [
          "--judgments",
          judgmentPath,
          "--output",
          join(repositoryLink, "aliased-output.json"),
        ],
        { manifestPath, repositoryRoot },
      ),
    /exact manifest target/u,
  );

  const realOutput = join(externalRoot, "real-output.json");
  const outputLink = join(externalRoot, "output-link.json");
  writeOwnerOnly(realOutput);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        [
          "--judgments",
          judgmentPath,
          "--output",
          relative(process.cwd(), realOutput),
        ],
        { manifestPath, repositoryRoot },
      ),
    /absolute path/u,
  );
  const externalOptions = ledger.parseManifestGeneratorOptions(
    ["--judgments", judgmentPath, "--output", realOutput],
    { manifestPath, repositoryRoot },
  );
  assert.equal(externalOptions.outputPath, realpathSync(realOutput));
  assert.equal(externalOptions.outputOwnerOnly, true);
  symlinkSync(realOutput, outputLink);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        ["--judgments", judgmentPath, "--output", outputLink],
        { manifestPath, repositoryRoot },
      ),
    /symbolic link/u,
  );

  const outputDirectory = join(externalRoot, "output-directory");
  mkdirSync(outputDirectory);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(
        ["--judgments", judgmentPath, "--output", outputDirectory],
        { manifestPath, repositoryRoot },
      ),
    /regular file/u,
  );

  const emitLink = join(externalRoot, "emit-link.jsonl");
  symlinkSync(realOutput, emitLink);
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(["--emit-inputs", emitLink], {
        manifestPath,
        repositoryRoot,
      }),
    /symbolic link/u,
  );
  assert.throws(
    () =>
      ledger.parseManifestGeneratorOptions(["--emit-inputs", outputDirectory], {
        manifestPath,
        repositoryRoot,
      }),
    /regular file/u,
  );
});

test("judgment index requires the exact audited capability id set", () => {
  const capabilityIds = auditedCapabilityIds();
  const records = capabilityIds.map((capabilityId) => ({
    input: { capability_id: capabilityId },
  }));
  assert.equal(capabilityIds.length > 0, true);
  assert.deepEqual(
    [...ledger.indexJudgmentRecords(records, capabilityIds).keys()],
    capabilityIds,
  );
  const missingCapabilityId = capabilityIds.at(-1);
  assert.throws(
    () => ledger.indexJudgmentRecords(records.slice(0, -1), capabilityIds),
    new RegExp(`missing capability ${missingCapabilityId}`, "u"),
  );
  assert.throws(
    () =>
      ledger.indexJudgmentRecords(
        [...records, { input: { capability_id: "capability-extra" } }],
        capabilityIds,
      ),
    /unexpected capability capability-extra/u,
  );
});

test("secure artifact writes are owner-only and never follow a final symlink", (t) => {
  const { externalRoot } = fixture(t);
  assert.equal(typeof ledger.writeValidatedArtifactSync, "function");

  const artifactPath = join(externalRoot, "artifact.jsonl");
  ledger.writeValidatedArtifactSync(artifactPath, "first\n", {
    ownerOnly: true,
  });
  assert.equal(readFileSync(artifactPath, "utf8"), "first\n");
  assert.equal(lstatSync(artifactPath).mode & 0o777, 0o600);

  chmodSync(artifactPath, 0o644);
  ledger.writeValidatedArtifactSync(artifactPath, "second\n", {
    ownerOnly: true,
  });
  assert.equal(readFileSync(artifactPath, "utf8"), "second\n");
  assert.equal(lstatSync(artifactPath).mode & 0o777, 0o600);

  const repositoryArtifactPath = join(externalRoot, "repository-artifact.json");
  writeFileSync(repositoryArtifactPath, "before\n", { mode: 0o644 });
  chmodSync(repositoryArtifactPath, 0o644);
  ledger.writeValidatedArtifactSync(repositoryArtifactPath, "after\n");
  assert.equal(readFileSync(repositoryArtifactPath, "utf8"), "after\n");
  assert.equal(lstatSync(repositoryArtifactPath).mode & 0o777, 0o644);

  const symlinkPath = join(externalRoot, "artifact-link.jsonl");
  symlinkSync(artifactPath, symlinkPath);
  assert.throws(
    () =>
      ledger.writeValidatedArtifactSync(symlinkPath, "unsafe\n", {
        ownerOnly: true,
      }),
    /symbolic link|ELOOP/u,
  );
  assert.equal(readFileSync(artifactPath, "utf8"), "second\n");
});
