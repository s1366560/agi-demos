import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { parse, parseAllDocuments } from 'yaml';

const PNPM_VERSION = '11.15.1';
const PNPM_INTEGRITY =
  '81350b07e53c9538a02f1f2303b4290fa2d7be04e56e2a970c4cc4b417dc761de196edabd49d55c7dc9580db81007c44143e4e3d7e462b3000d23c255122d065';
const PACKAGE_MANAGER_DECLARATION = `pnpm@${PNPM_VERSION}+sha512.${PNPM_INTEGRITY}`;
const PNPM_SETUP_ACTION = 'pnpm/action-setup@fc06bc1257f339d1d5d8b3a19a8cae5388b55320';
const NODE_SETUP_ACTION = 'actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020';
const repositoryRoot = fileURLToPath(new URL('../../../..', import.meta.url));
const desktopRoot = fileURLToPath(new URL('..', import.meta.url));

const readRepositoryFile = (path) =>
  readFileSync(new URL(path, `file://${repositoryRoot}/`), 'utf8');
const readDesktopFile = (path) => readFileSync(new URL(path, `file://${desktopRoot}/`), 'utf8');

const ciWorkflow = parse(readRepositoryFile('.github/workflows/ci.yml'));
const e2eWorkflow = parse(readRepositoryFile('.github/workflows/e2e.yml'));
const releaseWorkflow = parse(readRepositoryFile('.github/workflows/desktop-release.yml'));
const rootPackage = JSON.parse(readRepositoryFile('package.json'));
const webPackage = JSON.parse(readRepositoryFile('web/package.json'));
const desktopPackage = JSON.parse(readDesktopFile('package.json'));
const browserExtensionPackage = JSON.parse(
  readRepositoryFile('agi-stack/apps/browser-extension/package.json'),
);
const prototypePackage = JSON.parse(
  readRepositoryFile('design-prototype/memstack-desktop-agent-mission-control/package.json'),
);
const rootMakefile = readRepositoryFile('Makefile');
const webDockerfile = readRepositoryFile('web/Dockerfile');
const rootWorkspace = parse(readRepositoryFile('pnpm-workspace.yaml'));
const desktopWorkspace = parse(readDesktopFile('pnpm-workspace.yaml'));
const browserExtensionWorkspace = parse(
  readRepositoryFile('agi-stack/apps/browser-extension/pnpm-workspace.yaml'),
);
const prototypeWorkspace = parse(
  readRepositoryFile('design-prototype/memstack-desktop-agent-mission-control/pnpm-workspace.yaml'),
);
const desktopLockDocuments = parseAllDocuments(readDesktopFile('pnpm-lock.yaml')).map(
  (document) => {
    assert.deepEqual(document.errors, []);
    return document.toJSON();
  },
);
const makefile = readRepositoryFile('agi-stack/Makefile');
const browserBridgeSmoke = readRepositoryFile(
  'agi-stack/apps/browser-extension/scripts/smoke-bridge.mjs',
);

const pnpmSetupSteps = (job) =>
  job.steps.filter((step) => step.uses?.startsWith('pnpm/action-setup@'));
const nodeSetupSteps = (job) =>
  job.steps.filter((step) => step.uses?.startsWith('actions/setup-node@'));

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
      version: step.with['node-version'],
    })),
    [{ uses: NODE_SETUP_ACTION, version: '22' }],
  );
};

test('ordinary PR CI runs the complete desktop parity gate', () => {
  const webJob = ciWorkflow.jobs.web;
  const routeInventoryStep = webJob.steps.find(
    (step) => step.name === 'Verify desktop parity route inventory',
  );
  const routeInventoryTestsStep = webJob.steps.find(
    (step) => step.name === 'Test desktop parity route inventory',
  );
  assert.ok(
    routeInventoryTestsStep,
    'ordinary CI must run the production route inventory unit tests',
  );
  assert.equal(routeInventoryTestsStep.run, 'node --test scripts/web-route-inventory.test.mjs');
  assert.ok(routeInventoryStep, 'ordinary CI must reject a stale Web route inventory');
  assert.equal(routeInventoryStep.run, 'node scripts/web-route-inventory.mjs');

  const desktopJob = ciWorkflow.jobs['agi-stack-desktop-bundle'];
  assert.ok(desktopJob, 'ordinary CI must retain the desktop bundle job');

  const installBrowserIndex = desktopJob.steps.findIndex(
    (step) => step.name === 'Install desktop parity browser',
  );
  const installDependenciesIndex = desktopJob.steps.findIndex(
    (step) => step.name === 'Install desktop dependencies',
  );
  const parityGateIndex = desktopJob.steps.findIndex(
    (step) => step.name === 'Verify desktop parity',
  );
  assert.ok(
    installDependenciesIndex >= 0 && installDependenciesIndex < installBrowserIndex,
    'desktop dependencies must be installed before the parity browser',
  );
  assert.ok(installBrowserIndex >= 0, 'ordinary CI must install the parity browser');
  assert.ok(parityGateIndex > installBrowserIndex, 'parity must run after browser installation');
  assert.equal(desktopJob.steps[installDependenciesIndex].run, 'make desktop-deps');
  assert.equal(
    desktopJob.steps[installBrowserIndex]['working-directory'],
    'agi-stack/apps/desktop',
  );
  assert.equal(
    desktopJob.steps[installBrowserIndex].run,
    'corepack pnpm exec playwright install chromium',
  );
  assert.equal(desktopJob.steps[parityGateIndex].run, 'make desktop-parity-check');
  assert.match(
    makefile,
    /desktop-web-deps:[\s\S]*cd \.\.\/web && CI=true corepack pnpm install --frozen-lockfile/u,
  );
  assert.match(makefile, /desktop-route-inventory:\s+desktop-web-deps/u);
  assert.match(
    makefile,
    /desktop-parity-contract:\s+desktop-deps[\s\S]*generate-parity-manifest-v2\.mjs --check/u,
  );
  assert.match(
    makefile,
    /desktop-parity-contract:\s+desktop-deps[\s\S]*generate-parity-manifest-v3\.mjs --check/u,
  );
  assert.match(makefile, /desktop-parity-check:[^\n]*desktop-parity-contract/u);
  assert.match(makefile, /desktop-paired-browser-qa:\s+desktop-deps desktop-web-deps/u);

  const uploadEvidence = desktopJob.steps.find(
    (step) => step.name === 'Upload paired renderer evidence',
  );
  assert.ok(uploadEvidence, 'ordinary CI must retain successful paired renderer evidence');
  assert.equal(uploadEvidence.if, 'always()');
  assert.equal(uploadEvidence.with.path, 'agi-stack/apps/desktop/browser-qa/paired-results');
  assert.equal(uploadEvidence.with['if-no-files-found'], 'error');
  assert.equal(uploadEvidence.with['retention-days'], 30);
});

test('all JavaScript projects and delivery paths use one integrity-pinned pnpm toolchain', () => {
  assert.equal(rootPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(webPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(desktopPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(browserExtensionPackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(prototypePackage.packageManager, PACKAGE_MANAGER_DECLARATION);
  assert.equal(desktopPackage.devEngines, undefined);
  assert.equal(desktopPackage.pnpm, undefined);
  assert.equal(desktopPackage.devDependencies['electron-builder'], '26.15.3');
  assert.equal(
    desktopPackage.devDependencies.pnpm,
    PNPM_VERSION,
    'electron-builder subprocesses must resolve a project-local pinned pnpm',
  );
  assert.deepEqual(desktopWorkspace.packages, ['.']);
  assert.deepEqual(desktopWorkspace.allowBuilds, {
    '@scarf/scarf': false,
    'core-js': false,
    electron: true,
    'electron-winstaller': false,
    esbuild: true,
  });
  assert.equal(desktopWorkspace.enableGlobalVirtualStore, false);
  assert.equal(desktopLockDocuments.length, 2);
  assert.equal(
    desktopLockDocuments[0].importers['.'].packageManagerDependencies.pnpm.version,
    PNPM_VERSION,
  );
  assert.equal(
    desktopLockDocuments[0].importers['.'].packageManagerDependencies['@pnpm/exe'].version,
    PNPM_VERSION,
  );
  assert.ok(desktopLockDocuments[1].importers['.'].dependencies);
  assert.deepEqual(desktopLockDocuments[1].importers['.'].devDependencies.pnpm, {
    specifier: PNPM_VERSION,
    version: PNPM_VERSION,
  });
  assert.match(desktopPackage.scripts['package:electron'], /corepack pnpm exec electron-builder/u);
  assert.match(desktopPackage.scripts['release:electron'], /corepack pnpm exec electron-builder/u);
  assert.match(rootMakefile, /^PNPM\s+\?=\s+corepack pnpm$/mu);
  assert.match(rootMakefile, /cd web && \$\(PNPM\) install --frozen-lockfile/u);
  assert.doesNotMatch(webDockerfile, /npm install -g pnpm/u);
  assert.match(webDockerfile, /RUN corepack enable && corepack pnpm install --frozen-lockfile/u);
  assert.match(webDockerfile, /RUN corepack pnpm run build/u);
  assert.match(makefile, /^PNPM\s+\?=\s+corepack pnpm$/mu);

  assertFrontendToolchain(ciWorkflow.jobs.web);
  assertFrontendToolchain(ciWorkflow.jobs['agi-stack-desktop-bundle']);
  assertFrontendToolchain(e2eWorkflow.jobs['web-smoke']);
  assertFrontendToolchain(e2eWorkflow.jobs['backend-e2e']);

  const releasePnpmSteps = Object.values(releaseWorkflow.jobs).flatMap(pnpmSetupSteps);
  assert.ok(releasePnpmSteps.length > 0);
  assert.ok(releasePnpmSteps.every((step) => step.with.version === PNPM_VERSION));
  assert.ok(releasePnpmSteps.every((step) => step.uses === PNPM_SETUP_ACTION));
  const releaseNodeSteps = Object.values(releaseWorkflow.jobs).flatMap(nodeSetupSteps);
  assert.ok(releaseNodeSteps.length > 0);
  assert.ok(
    releaseNodeSteps.every(
      (step) => step.uses === NODE_SETUP_ACTION && step.with['node-version'] === '22',
    ),
  );

  const activeToolchainContract = JSON.stringify({
    packages: [webPackage, desktopPackage, browserExtensionPackage],
    ci: ciWorkflow,
    e2e: e2eWorkflow,
    release: releaseWorkflow,
  });
  assert.doesNotMatch(activeToolchainContract, /pmOnFail["']?\s*[:=]\s*["']?ignore/iu);

  const releaseBuilderCommands = releaseWorkflow.jobs.build.steps
    .map((step) => step.run)
    .filter((run) => typeof run === 'string' && run.includes('electron-builder'));
  assert.equal(releaseBuilderCommands.length, 3);
  assert.ok(
    releaseBuilderCommands.every((run) => run.startsWith('corepack pnpm exec electron-builder')),
  );

  const releaseEvidenceUpload = releaseWorkflow.jobs['parity-preflight'].steps.find(
    (step) => step.name === 'Upload paired renderer evidence',
  );
  assert.ok(releaseEvidenceUpload);
  assert.equal(releaseEvidenceUpload.if, 'always()');
  assert.equal(releaseEvidenceUpload.with.path, 'agi-stack/apps/desktop/browser-qa/paired-results');
  assert.equal(releaseEvidenceUpload.with['if-no-files-found'], 'error');
  assert.equal(releaseEvidenceUpload.with['retention-days'], 90);
});

test('install roots stay isolated behind pnpm-only lockfiles', () => {
  const pnpmLockfiles = [
    'pnpm-lock.yaml',
    'web/pnpm-lock.yaml',
    'agi-stack/apps/desktop/pnpm-lock.yaml',
    'agi-stack/apps/browser-extension/pnpm-lock.yaml',
    'design-prototype/memstack-desktop-agent-mission-control/pnpm-lock.yaml',
  ];
  const obsoleteLockfiles = [
    'package-lock.json',
    'yarn.lock',
    'web/package-lock.json',
    'agi-stack/apps/browser-extension/package-lock.json',
    'design-prototype/memstack-desktop-agent-mission-control/package-lock.json',
  ];

  assert.ok(pnpmLockfiles.every((path) => existsSync(new URL(path, `file://${repositoryRoot}/`))));
  assert.ok(
    obsoleteLockfiles.every((path) => !existsSync(new URL(path, `file://${repositoryRoot}/`))),
  );
  assert.equal(rootWorkspace.packages, undefined);
  assert.deepEqual(browserExtensionWorkspace.packages, []);
  assert.deepEqual(rootWorkspace.allowBuilds, {
    '@ladybugdb/core': true,
    '@scarf/scarf': false,
    gitnexus: false,
    'onnxruntime-node': false,
    protobufjs: false,
    sharp: false,
    'tree-sitter': false,
    'tree-sitter-c-sharp': false,
    'tree-sitter-cpp': false,
    'tree-sitter-go': false,
    'tree-sitter-java': false,
    'tree-sitter-javascript': false,
    'tree-sitter-php': false,
    'tree-sitter-python': false,
    'tree-sitter-ruby': false,
    'tree-sitter-rust': false,
    'tree-sitter-typescript': false,
  });
  assert.equal(prototypeWorkspace.packages, undefined);
  assert.deepEqual(prototypeWorkspace.allowBuilds, { esbuild: true });

  const rootLock = parse(readRepositoryFile('pnpm-lock.yaml'));
  const prototypeLock = parse(
    readRepositoryFile('design-prototype/memstack-desktop-agent-mission-control/pnpm-lock.yaml'),
  );
  assert.deepEqual(
    Object.keys(rootLock.importers['.'].devDependencies).sort(),
    Object.keys(rootPackage.devDependencies).sort(),
  );
  assert.deepEqual(
    Object.keys(prototypeLock.importers['.'].dependencies).sort(),
    Object.keys(prototypePackage.dependencies).sort(),
  );
});

test('browser bridge live smoke can register only inside its scratch Chromium profile', () => {
  assert.match(browserBridgeSmoke, /AGISTACK_BROWSER_BRIDGE_MANIFEST_DIR/u);
  assert.match(
    browserBridgeSmoke,
    /manifestPath[^\n]*expectedManifestPath|expectedManifestPath[^\n]*manifestPath/u,
  );
  assert.doesNotMatch(browserBridgeSmoke, /copyFileSync/u);
});

test('release matrix runs host-native sidecar permission tests before packaging', () => {
  assert.deepEqual(
    releaseWorkflow.jobs.build.strategy.matrix.include.map(({ platform }) => platform),
    ['macOS', 'Windows', 'Linux'],
  );
  const steps = releaseWorkflow.jobs.build.steps;
  const testIndex = steps.findIndex((step) => step.name === 'Test native Rust sidecar');
  const buildIndex = steps.findIndex((step) => step.name === 'Build native Rust sidecar');
  const universalBuildIndex = steps.findIndex(
    (step) => step.name === 'Build universal macOS Rust sidecar',
  );
  assert.ok(testIndex >= 0, 'every host platform must execute sidecar tests');
  assert.equal(
    steps[testIndex].run,
    'cargo test --manifest-path ../../Cargo.toml -p agistack-desktop-sidecar',
  );
  assert.ok(testIndex < buildIndex);
  assert.ok(testIndex < universalBuildIndex);
  assert.equal(steps[testIndex].if, undefined);
});
