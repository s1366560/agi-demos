import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  computeRendererTreeDigest,
  createPairedRendererBuildReceipt,
  serializePairedRendererBuildReceipt,
  snapshotRendererTree,
  validatePairedRendererBuildReceipt,
} from "../browser-qa/production-renderer-build-attestation.mjs";
import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

const desktopRoot = dirname(
  fileURLToPath(new URL("../package.json", import.meta.url)),
);
const repositoryRoot = fileURLToPath(new URL("../../../..", import.meta.url));
const makefileSource = readFileSync(
  join(repositoryRoot, "agi-stack/Makefile"),
  "utf8",
);
const pairedConfigSource = readFileSync(
  new URL("../browser-qa/paired-production.playwright.config.mjs", import.meta.url),
  "utf8",
);
const attestationSchema = JSON.parse(
  readFileSync(
    new URL(
      "../browser-qa/production-renderer-build-attestation.v1.schema.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

function makeRecipe(source, target) {
  const match = source.match(
    new RegExp(`^${target}:[^\\n]*\\n((?:\\t[^\\n]*(?:\\n|$))*)`, "mu"),
  );
  assert.ok(match, `Make target ${target} must exist`);
  return match[1];
}

function writeFixtureTree(root, reverse = false) {
  const files = [
    ["index.html", "<main>x</main>"],
    ["assets/app.js", "export{};"],
  ];
  for (const [relativePath, content] of reverse ? files.reverse() : files) {
    const path = join(root, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
  }
}

function withTemporaryDirectory(t) {
  const directory = mkdtempSync(
    join(tmpdir(), "agistack-renderer-attestation-"),
  );
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return directory;
}

test("paired production builds and previews the canonical Electron renderer output", () => {
  const recipe = makeRecipe(makefileSource, "desktop-paired-browser-qa");
  assert.match(recipe, /\$\(PNPM\) run qa:paired-production(?:\s|$)/u);
  assert.doesNotMatch(recipe, /run build(?::electron)?/u);

  assert.match(pairedConfigSource, /webServer:\s*\[/u);
  assert.match(pairedConfigSource, /--outDir dist/u);
  assert.match(pairedConfigSource, /--outDir out\/renderer/u);
  assert.match(pairedConfigSource, /AGISTACK_PAIRED_BUILD_RECEIPT/u);
  assert.match(pairedConfigSource, /AGISTACK_PAIRED_INVOCATION_NONCE/u);
});

test("renderer tree digest is stable across creation order and mtimes", (t) => {
  const temporaryDirectory = withTemporaryDirectory(t);
  const firstRoot = join(temporaryDirectory, "first");
  const secondRoot = join(temporaryDirectory, "second");
  writeFixtureTree(firstRoot);
  writeFixtureTree(secondRoot, true);
  utimesSync(
    join(secondRoot, "index.html"),
    new Date("2001-01-01T00:00:00Z"),
    new Date("2001-01-01T00:00:00Z"),
  );

  const first = snapshotRendererTree(firstRoot);
  const second = snapshotRendererTree(secondRoot);

  assert.deepEqual(first, second);
  assert.equal(
    first.tree_digest,
    "sha256:be5e66cf89f7ec2613b038dfabf408f4dc76f2fe0e755c5f7e883c0887873247",
  );
  assert.equal(first.file_count, 2);
  assert.equal(first.total_bytes, 23);
  assert.deepEqual(
    first.files.map((file) => file.path),
    ["assets/app.js", "index.html"],
  );
});

test("renderer tree digest binds file paths and bytes", (t) => {
  const temporaryDirectory = withTemporaryDirectory(t);
  const root = join(temporaryDirectory, "renderer");
  writeFixtureTree(root);
  const original = snapshotRendererTree(root);

  writeFileSync(join(root, "assets/app.js"), "export{1};");
  const changedBytes = snapshotRendererTree(root);
  assert.notEqual(changedBytes.tree_digest, original.tree_digest);

  rmSync(join(root, "assets/app.js"));
  writeFileSync(join(root, "assets/renamed.js"), "export{};");
  const changedPath = snapshotRendererTree(root);
  assert.notEqual(changedPath.tree_digest, original.tree_digest);
  assert.equal(
    computeRendererTreeDigest(original.files),
    original.tree_digest,
  );
});

test("renderer tree snapshot rejects missing entrypoints and symbolic links", (t) => {
  const temporaryDirectory = withTemporaryDirectory(t);
  const missingEntrypointRoot = join(temporaryDirectory, "missing-entrypoint");
  mkdirSync(missingEntrypointRoot, { recursive: true });
  writeFileSync(join(missingEntrypointRoot, "app.js"), "export{};");
  assert.throws(
    () => snapshotRendererTree(missingEntrypointRoot),
    /must contain index\.html/u,
  );

  if (process.platform !== "win32") {
    const linkedRoot = join(temporaryDirectory, "linked");
    writeFixtureTree(linkedRoot);
    symlinkSync(
      join(linkedRoot, "index.html"),
      join(linkedRoot, "linked-index.html"),
    );
    assert.throws(
      () => snapshotRendererTree(linkedRoot),
      /symbolic links/u,
    );
  }
});

function createReceiptFixture(t, sourceRevision = "a".repeat(40)) {
  const temporaryDirectory = withTemporaryDirectory(t);
  const repositoryRoot = join(temporaryDirectory, "repository");
  const webRoot = join(repositoryRoot, "web", "dist");
  const desktopRendererRoot = join(
    repositoryRoot,
    "agi-stack",
    "apps",
    "desktop",
    "out",
    "renderer",
  );
  writeFixtureTree(webRoot);
  writeFixtureTree(desktopRendererRoot);
  const canonicalRepositoryRoot = realpathSync(repositoryRoot);
  const receipt = createPairedRendererBuildReceipt({
    sourceRevision,
    headTree: "b".repeat(40),
    invocationNonce: "c".repeat(64),
    repositoryRoot: canonicalRepositoryRoot,
    orchestrationStartedAt: "2026-07-30T00:00:00.000Z",
    orchestrationCompletedAt: "2026-07-30T00:00:04.000Z",
    lockfiles: {
      web: {
        path: "web/pnpm-lock.yaml",
        sha256: "d".repeat(64),
      },
      desktop: {
        path: "agi-stack/apps/desktop/pnpm-lock.yaml",
        sha256: "e".repeat(64),
      },
    },
    builds: {
      web: {
        command: ["corepack", "pnpm", "run", "build"],
        canonical_cwd: join(canonicalRepositoryRoot, "web"),
        started_at: "2026-07-30T00:00:00.100Z",
        completed_at: "2026-07-30T00:00:01.900Z",
        exit_code: 0,
      },
      desktop_renderer: {
        command: ["corepack", "pnpm", "run", "build:electron"],
        canonical_cwd: join(
          canonicalRepositoryRoot,
          "agi-stack/apps/desktop",
        ),
        started_at: "2026-07-30T00:00:02.000Z",
        completed_at: "2026-07-30T00:00:03.900Z",
        exit_code: 0,
      },
    },
    toolchain: {
      node: "v22.0.0",
      web_pnpm: "10.24.0",
      desktop_pnpm: "11.15.1",
      vite_web: "7.3.0",
      electron_vite: "5.0.0",
      electron: "43.2.0",
    },
    outputSnapshots: {
      web: snapshotRendererTree(webRoot),
      desktop_renderer: snapshotRendererTree(desktopRendererRoot),
    },
  });
  return {
    receipt,
    repositoryRoot: canonicalRepositoryRoot,
    webRoot,
    desktopRendererRoot,
  };
}

test("paired receipt binds source, canonical roots, and live output bytes", (t) => {
  const {
    receipt,
    repositoryRoot,
    webRoot,
    desktopRendererRoot,
  } = createReceiptFixture(t);

  assert.equal(receipt.outputs.web.repo_relative_root, "web/dist");
  assert.equal(
    receipt.outputs.desktop_renderer.repo_relative_root,
    "agi-stack/apps/desktop/out/renderer",
  );
  assert.equal(receipt.outputs.web.preview_out_dir, "dist");
  assert.equal(
    receipt.outputs.desktop_renderer.preview_out_dir,
    "out/renderer",
  );
  assert.equal(receipt.toolchain.web_pnpm, "10.24.0");
  assert.equal(receipt.toolchain.desktop_pnpm, "11.15.1");
  assert.deepEqual(validateJsonSchema(attestationSchema, receipt), []);
  assert.deepEqual(
    validatePairedRendererBuildReceipt(receipt, {
      expectedSourceRevision: "a".repeat(40),
      expectedInvocationNonce: "c".repeat(64),
      repositoryRoot,
      webRoot,
      desktopRendererRoot,
    }),
    [],
  );

  const serialized = serializePairedRendererBuildReceipt(receipt);
  assert.equal(serialized.at(-1), 10);
  assert.deepEqual(JSON.parse(serialized.toString("utf8")), receipt);

  writeFileSync(join(desktopRendererRoot, "assets/app.js"), "tampered");
  assert.equal(
    validatePairedRendererBuildReceipt(receipt, {
      expectedSourceRevision: "a".repeat(40),
      repositoryRoot,
      webRoot,
      desktopRendererRoot,
    }).some((error) =>
      error.includes("desktop_renderer live tree digest does not match"),
    ),
    true,
  );
});

test("paired receipt validator rejects internally forged metadata", (t) => {
  const { receipt } = createReceiptFixture(t, "b".repeat(40));
  const forged = structuredClone(receipt);
  forged.outputs.web.tree_digest = `sha256:${"0".repeat(64)}`;
  forged.outputs.web.file_count += 1;
  forged.outputs.web.total_bytes += 1;

  const errors = validatePairedRendererBuildReceipt(forged, {
    expectedSourceRevision: "c".repeat(40),
  });
  assert.equal(
    errors.some((error) => error.includes("source_revision does not match")),
    true,
  );
  assert.equal(
    errors.some((error) => error.includes("web tree_digest is invalid")),
    true,
  );
  assert.equal(
    errors.some((error) => error.includes("web file_count is invalid")),
    true,
  );
  assert.equal(
    errors.some((error) => error.includes("web total_bytes is invalid")),
    true,
  );

  const legacyToolchain = structuredClone(receipt);
  legacyToolchain.toolchain.pnpm = "11.15.1";
  delete legacyToolchain.toolchain.web_pnpm;
  delete legacyToolchain.toolchain.desktop_pnpm;
  const legacyErrors =
    validatePairedRendererBuildReceipt(legacyToolchain);
  assert.equal(
    legacyErrors.some((error) => error.includes("toolchain.web_pnpm")),
    true,
  );
  assert.equal(
    legacyErrors.some((error) => error.includes("toolchain.desktop_pnpm")),
    true,
  );
  assert.notDeepEqual(
    validateJsonSchema(attestationSchema, legacyToolchain),
    [],
  );
});
