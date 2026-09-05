import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function readSource(path) {
  return ts.createSourceFile(path, readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function find(source, predicate) {
  let result;
  const visit = (node) => {
    if (result) return;
    if (predicate(node)) result = node;
    else ts.forEachChild(node, visit);
  };
  visit(source);
  return result;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function hookHarness({ mode = 'cloud', review = Promise.resolve(), detail } = {}) {
  const source = readSource('features/settings/useSkillPackageManagement.ts');
  const declaration = find(source, (node) => ts.isVariableDeclaration(node)
    && ts.isIdentifier(node.name) && node.name.text === 'processEvolutionJob');
  assert.ok(declaration && ts.isCallExpression(declaration.initializer));
  const callback = declaration.initializer.arguments[0];
  const code = ts.transpileModule(`return ${callback.getText(source)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const config = Object.freeze({ mode, tenantId: 'tenant-one', projectId: 'project-current' });
  const evolutionDialog = { key: 'dialog-one', canManage: true, processingJobId: null,
    skill: { id: 'skill-reviewer' }, detail: null };
  const state = { dialog: evolutionDialog, error: null, reviews: [], legacy: [],
    detailReads: [], reloads: 0, selected: [] };
  const contextKeyRef = { current: 'context-one' };
  const tenantEvolutionOperationsV2 = {
    reviewTenantEvolutionJob(input) { state.reviews.push(input); return review; },
  };
  const bindings = {
    config, evolutionDialog, contextKey: 'context-one', contextKeyRef,
    tenantEvolutionOperationsV2,
    setEvolutionError: (error) => { state.error = error; },
    setEvolutionDialog: (update) => { state.dialog = update(state.dialog); },
    evolutionClient: {
      getManagedSkillEvolution(id) {
        state.detailReads.push(id);
        return detail ?? Promise.resolve({ skill_id: id, jobs: [] });
      },
    },
    onReload: async () => { state.reloads += 1; },
    onSelected: (id) => { state.selected.push(id); },
    errorMessage: (error) => error instanceof Error ? error.message : String(error),
  };
  return { state, config, contextKeyRef, tenantEvolutionOperationsV2,
    run: new Function(...Object.keys(bindings), code)(...Object.values(bindings)) };
}

test('applying a skill job uses required V2 tenant authority, then reloads and selects', async () => {
  const harness = hookHarness();
  await harness.run('job-apply', 'apply');
  assert.deepEqual(harness.state.reviews, [{
    config: harness.config,
    scope: { authority: 'cloud', tenantId: 'tenant-one' },
    jobId: 'job-apply', action: 'apply',
  }]);
  assert.deepEqual(harness.state.legacy, []);
  assert.deepEqual(harness.state.detailReads, ['skill-reviewer']);
  assert.equal(harness.state.reloads, 1);
  assert.deepEqual(harness.state.selected, ['skill-reviewer']);
  assert.equal(harness.state.dialog.processingJobId, null);
});

test('rejecting a skill job refreshes detail without reloading or selecting', async () => {
  const harness = hookHarness({ mode: 'local' });
  await harness.run('job-reject', 'reject');
  assert.deepEqual(harness.state.reviews, [{
    config: harness.config,
    scope: { authority: 'local', tenantId: 'tenant-one' },
    jobId: 'job-reject', action: 'reject',
  }]);
  assert.deepEqual(harness.state.legacy, []);
  assert.deepEqual(harness.state.detailReads, ['skill-reviewer']);
  assert.equal(harness.state.reloads, 0);
  assert.deepEqual(harness.state.selected, []);
});

test('V2 rejection is shown without retrying a static mutation or refreshing resources', async () => {
  const request = deferred();
  const harness = hookHarness({ review: request.promise });
  const action = harness.run('job-denied', 'apply');
  request.reject(new Error('missing_service_provider'));
  await action;
  assert.equal(harness.state.reviews.length, 1);
  assert.deepEqual(harness.state.legacy, []);
  assert.equal(harness.state.error, 'missing_service_provider');
  assert.deepEqual(harness.state.detailReads, []);
  assert.equal(harness.state.reloads, 0);
  assert.deepEqual(harness.state.selected, []);
  assert.equal(harness.state.dialog.processingJobId, null);
});

test('review completion after a context switch cannot reload or select the new context', async () => {
  const request = deferred();
  const harness = hookHarness({ review: request.promise });
  const action = harness.run('job-old', 'apply');
  harness.contextKeyRef.current = 'context-two';
  const currentDialog = { key: 'new-dialog', processingJobId: 'new-job' };
  harness.state.dialog = currentDialog;
  request.resolve();
  await action;
  assert.equal(harness.state.reloads, 0);
  assert.deepEqual(harness.state.selected, []);
  assert.equal(harness.state.dialog, currentDialog);
  assert.equal(harness.state.error, null);
});

test('late detail completion does not select a skill after changing context', async () => {
  const detail = deferred();
  const harness = hookHarness({ detail: detail.promise });
  const action = harness.run('job-apply', 'apply');
  await Promise.resolve();
  assert.equal(harness.state.reloads, 1);
  harness.contextKeyRef.current = 'context-two';
  const currentDialog = { key: 'new-dialog' };
  harness.state.dialog = currentDialog;
  detail.resolve({ skill_id: 'skill-reviewer', jobs: [] });
  await action;
  assert.deepEqual(harness.state.selected, []);
  assert.equal(harness.state.dialog, currentDialog);
});

test('both static skill job mutation APIs are retired from client classes', () => {
  const retired = new Set(['applyManagedSkillEvolutionJob', 'rejectManagedSkillEvolutionJob',
    'mutateManagedSkillEvolutionJob']);
  assert.equal(existsSync(new URL('../src/api/managedResourcesClient.ts', import.meta.url)), false);
  for (const path of ['api/client.ts']) {
    const source = readSource(path);
    const method = find(source, (node) => ts.isMethodDeclaration(node)
      && retired.has(node.name.getText(source)));
    assert.ok(!method, `${path} still declares a static job mutation method`);
  }
});

test('the review hook subscribes to the injected V2 operations identity', () => {
  const source = readSource('features/settings/useSkillPackageManagement.ts');
  const declaration = find(source, (node) => ts.isVariableDeclaration(node)
    && ts.isIdentifier(node.name) && node.name.text === 'processEvolutionJob');
  const dependencies = declaration.initializer.arguments[1];
  assert.ok(ts.isArrayLiteralExpression(dependencies));
  assert.ok(dependencies.elements.some((node) => ts.isIdentifier(node)
    && node.text === 'tenantEvolutionOperationsV2'));
});
