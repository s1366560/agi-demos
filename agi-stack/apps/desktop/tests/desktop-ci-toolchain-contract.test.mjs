import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { parse, parseAllDocuments } from "yaml";

const PNPM_VERSION = "11.15.1";
const PNPM_INTEGRITY =
  "81350b07e53c9538a02f1f2303b4290fa2d7be04e56e2a970c4cc4b417dc761de196edabd49d55c7dc9580db81007c44143e4e3d7e462b3000d23c255122d065";
const PACKAGE_MANAGER_DECLARATION =
  `pnpm@${PNPM_VERSION}+sha512.${PNPM_INTEGRITY}`;
const PNPM_SETUP_ACTION =
  "pnpm/action-setup@fc06bc1257f339d1d5d8b3a19a8cae5388b55320";
const NODE_SETUP_ACTION =
  "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020";
const repositoryRoot = fileURLToPath(new URL("../../../..", import.meta.url));
const desktopRoot = fileURLToPath(new URL("..", import.meta.url));

const readRepositoryFile = (path) =>
  readFileSync(new URL(path, `file://${repositoryRoot}/`), "utf8");
const readDesktopFile = (path) =>
  readFileSync(new URL(path, `file://${desktopRoot}/`), "utf8");

const ciWorkflow = parse(readRepositoryFile(".github/workflows/ci.yml"));
const e2eWorkflow = parse(readRepositoryFile(".github/workflows/e2e.yml"));
const releaseWorkflow = parse(
  readRepositoryFile(".github/workflows/desktop-release.yml"),
);
const webPackage = JSON.parse(readRepositoryFile("web/package.json"));
const desktopPackage = JSON.parse(readDesktopFile("package.json"));
const desktopWorkspace = parse(readDesktopFile("pnpm-workspace.yaml"));
const desktopLockDocuments = parseAllDocuments(
  readDesktopFile("pnpm-lock.yaml"),
).map((document) => {
  assert.deepEqual(document.errors, []);
  return document.toJSON();
});
const makefile = readRepositoryFile("agi-stack/Makefile");

const pnpmSetupSteps = (job) =>
  job.steps.filter((step) => step.uses?.startsWith("pnpm/action-setup@"));
const nodeSetupSteps = (job) =>
  job.steps.filter((step) => step.uses?.startsWith("actions/setup-node@"));

const assertFrontendToolchain = (job) => {
  assert.deepEqual(
    pnpmSetupSteps(job).map((step) => ({
      uses: step.uses,
      version: step.with.version,
    })),
    [{ uses: PNPM_SETUP_ACTION, version: PNPM_VERSION }],
  );
  assert.deepEqual(
    nodeSetupSteps(job).map((step) => ({
      uses: step.uses,
      version: step.with["node-version"],
    })),
    [{ uses: NODE_SETUP_ACTION, version: "22" }],
  );
};

test("ordinary PR CI runs the complete desktop parity gate", () => {
  const webJob = ciWorkflow.jobs.web;
  const routeInventoryStep = webJob.steps.find(
    (step) => step.name === "Verify desktop parity route inventory",
  );
  const routeInventoryTestsStep = webJob.steps.find(
    (step) => step.name === "Test desktop parity route inventory",
  );
  assert.ok(
    routeInventoryTestsStep,
    "ordinary CI must run the production route inventory unit tests",
  );
  assert.equal(
    routeInventoryTestsStep.run,
    "node --test scripts/web-route-inventory.test.mjs",
  );
  assert.ok(
    routeInventoryStep,
    "ordinary CI must reject a stale Web route inventory",
  );
  assert.equal(routeInventoryStep.run, "node scripts/web-route-inventory.mjs");

  const desktopJob = ciWorkflow.jobs["agi-stack-desktop-bundle"];
  assert.ok(desktopJob, "ordinary CI must retain the desktop bundle job");

  const installBrowserIndex = desktopJob.steps.findIndex(
    (step) => step.name === "Install desktop parity browser",
  );
  const installDependenciesIndex = desktopJob.steps.findIndex(
    (step) => step.name === "Install desktop dependencies",
  );
  const parityGateIndex = desktopJob.steps.findIndex(
    (step) => step.name === "Verify desktop parity",
  );
  assert.ok(
    installDependenciesIndex >= 0 &&
      installDependenciesIndex < installBrowserIndex,
    "desktop dependencies must be installed before the parity browser",
  );
  assert.ok(
    installBrowserIndex >= 0,
    "ordinary CI must install the parity browser",
  );
  assert.ok(
    parityGateIndex > installBrowserIndex,
    "parity must run after browser installation",
  );
  assert.equal(
    desktopJob.steps[installDependenciesIndex].run,
    "make desktop-deps",
  );
  assert.equal(
    desktopJob.steps[installBrowserIndex]["working-directory"],
    "agi-stack/apps/desktop",
  );
  assert.equal(
    desktopJob.steps[installBrowserIndex].run,
    "corepack pnpm exec playwright install chromium",
  );
  assert.equal(
    desktopJob.steps[parityGateIndex].run,
    "make desktop-parity-check",
  );
  assert.match(
    makefile,
    /desktop-web-deps:[\s\S]*cd \.\.\/web && CI=true corepack pnpm install --frozen-lockfile/u,
  );
  assert.match(makefile, /desktop-route-inventory:\s+desktop-web-deps/u);
  assert.match(
    makefile,
    /desktop-parity-contract:\s+desktop-deps[\s\S]*generate-parity-manifest-v2\.mjs --check/u,
  );
  assert.match(makefile, /desktop-parity-check:[^\n]*desktop-parity-contract/u);
  assert.match(
    makefile,
    /desktop-paired-browser-qa:\s+desktop-deps desktop-web-deps/u,
  );

  const uploadEvidence = desktopJob.steps.find(
    (step) => step.name === "Upload paired renderer evidence",
  );
  assert.ok(
    uploadEvidence,
    "ordinary CI must retain successful paired renderer evidence",
  );
  assert.equal(uploadEvidence.if, "always()");
  assert.equal(
    uploadEvidence.with.path,
    "agi-stack/apps/desktop/browser-qa/paired-results",
  );
  assert.equal(uploadEvidence.with["if-no-files-found"], "error");
  assert.equal(uploadEvidence.with["retention-days"], 30);
});

test("Web, Desktop, CI, E2E, and release use one integrity-pinned pnpm toolchain", () => {
  assert.equal(webPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(desktopPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(desktopPackage.devEngines, undefined);
  assert.equal(desktopPackage.pnpm, undefined);
  assert.equal(desktopPackage.devDependencies["electron-builder"], "26.15.3");
  assert.deepEqual(desktopWorkspace.packages, ["."]);
  assert.deepEqual(desktopWorkspace.allowBuilds, {
    "@scarf/scarf": false,
    "core-js": false,
    electron: true,
    "electron-winstaller": false,
    esbuild: true,
  });
  assert.equal(desktopWorkspace.enableGlobalVirtualStore, false);
  assert.equal(desktopLockDocuments.length, 2);
  assert.equal(
    desktopLockDocuments[0].importers["."].packageManagerDependencies.pnpm
      .version,
    PNPM_VERSION,
  );
  assert.equal(
    desktopLockDocuments[0].importers["."].packageManagerDependencies[
      "@pnpm/exe"
    ].version,
    PNPM_VERSION,
  );
  assert.ok(desktopLockDocuments[1].importers["."].dependencies);
  assert.match(
    desktopPackage.scripts["package:electron"],
    /corepack pnpm exec electron-builder/u,
  );
  assert.match(
    desktopPackage.scripts["release:electron"],
    /corepack pnpm exec electron-builder/u,
  );
  assert.match(makefile, /^PNPM\s+\?=\s+corepack pnpm$/mu);

  assertFrontendToolchain(ciWorkflow.jobs.web);
  assertFrontendToolchain(ciWorkflow.jobs["agi-stack-desktop-bundle"]);
  assertFrontendToolchain(e2eWorkflow.jobs["web-smoke"]);
  assertFrontendToolchain(e2eWorkflow.jobs["backend-e2e"]);

  const releasePnpmSteps = Object.values(releaseWorkflow.jobs).flatMap(
    pnpmSetupSteps,
  );
  assert.ok(releasePnpmSteps.length > 0);
  assert.ok(
    releasePnpmSteps.every((step) => step.with.version === PNPM_VERSION),
  );
  assert.ok(
    releasePnpmSteps.every((step) => step.uses === PNPM_SETUP_ACTION),
  );
  const releaseNodeSteps = Object.values(releaseWorkflow.jobs).flatMap(
    nodeSetupSteps,
  );
  assert.ok(releaseNodeSteps.length > 0);
  assert.ok(
    releaseNodeSteps.every(
      (step) =>
        step.uses === NODE_SETUP_ACTION && step.with["node-version"] === "22",
    ),
  );

  const activeToolchainContract = JSON.stringify({
    packages: [webPackage, desktopPackage],
    ci: ciWorkflow,
    e2e: e2eWorkflow,
    release: releaseWorkflow,
  });
  assert.doesNotMatch(
    activeToolchainContract,
    /pmOnFail["']?\s*[:=]\s*["']?ignore/iu,
  );

  const releaseBuilderCommands = releaseWorkflow.jobs.build.steps
    .map((step) => step.run)
    .filter(
      (run) => typeof run === "string" && run.includes("electron-builder"),
    );
  assert.equal(releaseBuilderCommands.length, 3);
  assert.ok(
    releaseBuilderCommands.every((run) =>
      run.startsWith("corepack pnpm exec electron-builder"),
    ),
  );

  const releaseEvidenceUpload = releaseWorkflow.jobs[
    "parity-preflight"
  ].steps.find((step) => step.name === "Upload paired renderer evidence");
  assert.ok(releaseEvidenceUpload);
  assert.equal(releaseEvidenceUpload.if, "always()");
  assert.equal(
    releaseEvidenceUpload.with.path,
    "agi-stack/apps/desktop/browser-qa/paired-results",
  );
  assert.equal(releaseEvidenceUpload.with["if-no-files-found"], "error");
  assert.equal(releaseEvidenceUpload.with["retention-days"], 90);
});
