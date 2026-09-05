import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function sourceFile(path) {
  return ts.createSourceFile(path, readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function findNode(source, predicate) {
  let result;
  function visit(node) {
    if (result) return;
    if (predicate(node)) result = node;
    else ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(result, 'production callback must exist');
  return result;
}

function compile(node, source, bindings) {
  const code = ts.transpileModule(`const callback = ${node.getText(source)}; return callback;`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  return new Function(...Object.keys(bindings), code)(...Object.values(bindings));
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function catalogHarness() {
  const source = sourceFile('features/chat/ComposerPlusMenu.tsx');
  const effect = findNode(source, (node) => ts.isCallExpression(node)
    && node.expression.getText(source) === 'useEffect'
    && node.arguments[0]?.getText(source).includes('loadComposerCatalog(api,'));
  const pending = deferred();
  const api = {};
  const result = { catalog: null, error: null, requests: 0 };
  const bindings = {
    api, catalog: null, open: true, catalogApiRef: { current: api }, AbortController,
    loadComposerCatalog: () => { result.requests += 1; return pending.promise; },
    setCatalog: (value) => { result.catalog = value; },
    setCatalogState: (state) => { result.catalog = state?.value ?? null; },
    setCatalogError: (value) => { result.error = value; },
  };
  return { source, effect, pending, result, bindings,
    run: () => compile(effect.arguments[0], source, bindings)() };
}

test('composer ignores a successful response after its request was cancelled', async () => {
  const harness = catalogHarness();
  const cleanup = harness.run();
  cleanup();
  harness.pending.resolve({ subagents: [{ id: 'old' }] });
  await harness.pending.promise;
  await Promise.resolve();
  assert.equal(harness.result.catalog, null);
});

test('composer rejects the previous API response before effect cleanup runs', async () => {
  const harness = catalogHarness();
  harness.run();
  harness.bindings.catalogApiRef.current = {};
  harness.pending.resolve({ subagents: [{ id: 'other-tenant' }] });
  await harness.pending.promise;
  await Promise.resolve();
  assert.equal(harness.result.catalog, null);
});

test('composer reuses a catalog during one open session and hides it for another API', () => {
  const harness = catalogHarness();
  const value = { subagents: [{ id: 'current' }] };
  harness.bindings.catalog = value;
  harness.run();
  assert.equal(harness.result.requests, 0);
  const catalog = findNode(harness.source, (node) => ts.isVariableDeclaration(node)
    && ts.isIdentifier(node.name) && node.name.text === 'catalog');
  assert.equal(compile(catalog.initializer, harness.source,
    { api: harness.bindings.api, catalogState: { api: {}, value } }), null);
  assert.equal(compile(catalog.initializer, harness.source,
    { api: harness.bindings.api, catalogState: { api: harness.bindings.api, value } }), value);
});

test('opening the composer menu again clears the loaded catalog and previous error', () => {
  const source = sourceFile('features/chat/ComposerPlusMenu.tsx');
  const openMenu = findNode(source, (node) => ts.isFunctionDeclaration(node)
    && node.name?.text === 'openMenu');
  const state = { catalog: { subagents: [{ id: 'before-create' }] },
    error: 'previous request failed', open: false };
  const open = compile(openMenu, source, {
    setCatalogState: (value) => { state.catalog = value; },
    setCatalogError: (value) => { state.error = value; },
    setOpen: (value) => { state.open = value; },
  });
  open();
  assert.deepEqual(state, { catalog: null, error: null, open: true });
  const harness = catalogHarness();
  harness.bindings.catalog = state.catalog;
  harness.bindings.open = state.open;
  const cleanup = harness.run();
  assert.equal(harness.result.requests, 1, 'reopening must fetch newly created SubAgents');
  cleanup();
});

function toggleHarness() {
  const source = sourceFile('features/settings/SettingsWindow.tsx');
  const toggle = findNode(source, (node) => ts.isVariableDeclaration(node)
    && ts.isIdentifier(node.name) && node.name.text === 'toggleResource');
  const requests = [];
  const result = { busy: null, reloads: 0, error: null };
  const refs = { activeSectionRef: { current: 'subagents' },
    resourceContextKeyRef: { current: 'tenant-a' }, resourceActionRequestId: { current: 0 } };
  const bindings = {
    ...refs, isResourceSection: true, section: 'subagents', resourceContextKey: 'tenant-a',
    config: { mode: 'cloud' }, auth: { user: { roles: ['admin'] } },
    managedResourceManagementAllowed: () => true,
    managedResourceAction: () => ({ kind: 'set_subagent_enabled', nextActive: true }),
    setActionBusyId: (id) => { result.busy = id; },
    setResourceActionError: (error) => { result.error = error; },
    ManagedResourcesClient: class {},
    tenantSubAgentDefinitionsClientV2: { setManagedSubAgentEnabled: () => {
      const request = deferred(); requests.push(request); return request.promise;
    } },
    loadResources: async () => { result.reloads += 1; },
  };
  return { refs, bindings, requests, result,
    run: (id) => compile(toggle.initializer, source, bindings)({ id, enabled: false }) };
}

test('an old tenant toggle cannot clear the next tenant action busy state', async () => {
  const harness = toggleHarness();
  const first = harness.run('a');
  harness.refs.resourceContextKeyRef.current = 'tenant-b';
  harness.bindings.resourceContextKey = 'tenant-b';
  const second = harness.run('b');
  harness.requests[0].resolve();
  await first;
  assert.equal(harness.result.busy, 'b');
  assert.equal(harness.result.reloads, 0);
  harness.requests[1].resolve();
  await second;
  assert.equal(harness.result.busy, null);
  assert.equal(harness.result.reloads, 1);
});

test('an older toggle of the same resource cannot finish a newer action', async () => {
  const harness = toggleHarness();
  const first = harness.run('same-id');
  const second = harness.run('same-id');
  harness.requests[0].resolve();
  await first;
  assert.equal(harness.result.busy, 'same-id');
  assert.equal(harness.result.reloads, 0);
  harness.requests[1].resolve();
  await second;
  assert.equal(harness.result.busy, null);
  assert.equal(harness.result.reloads, 1);
});
