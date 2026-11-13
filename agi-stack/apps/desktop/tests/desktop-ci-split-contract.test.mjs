import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { parseDocument } from 'yaml';

const repositoryRoot = fileURLToPath(new URL('../../../..', import.meta.url));

const readRepositoryFile = (path) =>
  readFileSync(new URL(path, `file://${repositoryRoot}/`), 'utf8');

const parseWorkflow = (path) => {
  const source = readRepositoryFile(path);
  const document = parseDocument(source, { uniqueKeys: true });
  assert.deepEqual(
    document.errors.map((error) => error.message),
    [],
    `${path} must be valid YAML`,
  );
  return { source, workflow: document.toJSON() };
};

const stepRuns = (job) => job.steps.map((step) => step.run).filter((run) => typeof run === 'string');

test('pull request desktop gate keeps its check name and drops installer packaging', () => {
  const { source, workflow } = parseWorkflow('.github/workflows/ci.yml');
  const job = workflow.jobs['agi-stack-desktop-bundle'];
  assert.equal(job.name, 'agi-stack Desktop Bundle');
  assert.equal(job.needs, 'changes');
  assert.equal(job.if, "needs.changes.outputs.agi == 'true'");
  assert.equal(job['runs-on'], 'macos-latest');
  assert.equal(job['timeout-minutes'], 70);
  assert.equal(job.environment, undefined);
  assert.equal(job.permissions, undefined);
  assert.deepEqual(workflow.permissions, { contents: 'read' });

  const runs = stepRuns(job);
  assert.ok(runs.some((run) => run.includes('make desktop-test')));
  assert.ok(runs.some((run) => run.trim() === 'make desktop-icons'));
  assert.ok(runs.some((run) => run.trim() === 'make desktop-electron-build'));
  assert.equal(
    runs.some((run) => /make desktop-bundle\b/u.test(run)),
    false,
  );
  assert.equal(
    job.steps.some((step) => String(step.uses ?? '').startsWith('actions/upload-artifact@')),
    false,
  );
  assert.doesNotMatch(source, /agi-stack\/apps\/desktop\/release\/\*\.dmg/u);
  assert.doesNotMatch(JSON.stringify(job), /secrets\./u);
  assert.doesNotMatch(JSON.stringify(job), /desktop-release-signing/u);
  assert.equal(workflow.on.pull_request.branches.includes('main'), true);
  assert.equal(workflow.on.push.branches.includes('main'), true);
});

test('manual bundle verification cannot publish or select an untrusted ref', () => {
  const { source, workflow } = parseWorkflow('.github/workflows/desktop-bundle-verify.yml');
  assert.deepEqual(Object.keys(workflow.on), ['workflow_dispatch']);
  assert.equal(workflow.on.workflow_dispatch, null);
  assert.equal(workflow.on.pull_request, undefined);
  assert.equal(workflow.on.push, undefined);
  assert.deepEqual(workflow.permissions, { contents: 'read' });
  assert.equal(workflow.concurrency['cancel-in-progress'], false);

  const job = workflow.jobs.verify;
  assert.notEqual(job.name, 'agi-stack Desktop Bundle');
  assert.deepEqual(job.permissions, { contents: 'read' });
  assert.equal(job.environment, undefined);
  assert.equal(job['runs-on'], 'macos-latest');
  assert.equal(job['timeout-minutes'], 70);

  const checkout = job.steps.find((step) => String(step.uses ?? '').startsWith('actions/checkout@'));
  assert.equal(checkout.with['persist-credentials'], false);
  assert.equal(checkout.with.ref, undefined);
  assert.equal(checkout.with.repository, undefined);

  const runs = stepRuns(job);
  assert.ok(runs.some((run) => run.trim() === 'make desktop-bundle'));
  assert.ok(runs.some((run) => run.trim() === 'make desktop-bundle-smoke'));
  assert.equal(runs.some((run) => run.includes('electron-builder')), false);
  assert.equal(runs.some((run) => run.includes('gh release')), false);

  const upload = job.steps.find((step) =>
    String(step.uses ?? '').startsWith('actions/upload-artifact@'),
  );
  assert.equal(upload.with.name, 'desktop-bundle-verify');
  assert.equal(upload.with['if-no-files-found'], 'error');
  assert.doesNotMatch(source, /\$\{\{\s*secrets\./u);
  assert.doesNotMatch(source, /desktop-release-signing/u);
  assert.doesNotMatch(source, /notarytool|CSC_|APPLE_|WIN_CSC_|CODESIGN_IDENTITY/u);
  assert.doesNotMatch(source, /github\.event\.inputs/u);
  for (const match of source.matchAll(/uses:\s*[^@\s]+@([^\s#]+)/gu)) {
    assert.match(match[1], /^[a-f0-9]{40}$/u);
  }
});

test('protected tag release still verifies packages before publish', () => {
  const { workflow } = parseWorkflow('.github/workflows/desktop-release.yml');
  assert.deepEqual(workflow.on.push.tags, ['v*']);
  assert.equal(workflow.on.pull_request, undefined);
  assert.equal(workflow.jobs.authorize.environment, undefined);
  assert.equal(workflow.jobs.tests.environment, undefined);
  assert.equal(workflow.jobs.build.environment, 'desktop-release-signing');
  assert.equal(workflow.jobs['stage-draft'].environment, undefined);
  assert.deepEqual(workflow.jobs.build.permissions, { contents: 'read' });
  assert.deepEqual(workflow.jobs['stage-draft'].needs, ['authorize', 'build']);
  assert.deepEqual(workflow.jobs['stage-draft'].permissions, {
    actions: 'read',
    contents: 'write',
  });

  const buildRuns = stepRuns(workflow.jobs.build);
  assert.ok(buildRuns.some((run) => run.includes('node scripts/verify-release-artifacts.mjs')));
  assert.ok(buildRuns.some((run) => run.includes('node scripts/install-launch-smoke.mjs')));
  assert.ok(buildRuns.some((run) => run.includes('node scripts/smoke-update-drill.mjs')));
  const publish = workflow.jobs['stage-draft'].steps.find(
    (step) => step.name === 'Publish verified assets',
  );
  assert.match(publish.run, /gh release edit/u);
  assert.match(publish.run, /--draft=false/u);
});

test('electron build target stays separate from the installer target', () => {
  const makefile = readRepositoryFile('agi-stack/Makefile');
  assert.match(
    makefile,
    /^desktop-electron-build: ## .*$\n\tcd \$\(DESKTOP_APP_DIR\) && \$\(PNPM\) run build:electron$/mu,
  );
  assert.match(
    makefile,
    /^desktop-bundle: desktop-deps desktop-icons ## .*$\n\tcd \$\(DESKTOP_APP_DIR\) && \$\(PNPM\) run package:electron$/mu,
  );
  assert.match(
    makefile,
    /^desktop-test: desktop-deps desktop-cua-repl ## /mu,
  );
  const electronBuild = makefile.slice(
    makefile.indexOf('\ndesktop-electron-build:'),
    makefile.indexOf('\ndesktop-icons:'),
  );
  assert.doesNotMatch(electronBuild, /desktop-bundle|package:electron|--release/u);
});
