import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const {
  createProjectMemoriesController,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/projectMemoriesController.js');
const initialScope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
function snapshot(scope, page, total = 101) {
  return {
    scope,
    scopeRevision: 1,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_memories_actions_partial',
    allowedActions: ['view', 'list'],
    memories: [
      {
        id: `memory-${scope.projectId}-${page}`,
        title: `Page ${page}`,
        content: 'Content',
        processingStatus: 'COMPLETED',
      },
    ],
    total,
    page,
    pageSize: 50,
  };
}
function pageComponent() {
  const source = readFileSync(
    new URL('../src/features/project-knowledge/ProjectKnowledgePage.tsx', import.meta.url),
    'utf8',
  );
  const module = { exports: {} };
  new Function(
    'require',
    'module',
    'exports',
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText,
  )(
    (name) => (name === '../../i18n' ? { useI18n: () => ({ t: (key) => key }) } : require(name)),
    module,
    module.exports,
  );
  return module.exports.ProjectKnowledgePage;
}
function buttons(element) {
  if (Array.isArray(element)) return element.flatMap(buttons);
  if (!element || typeof element !== 'object') return [];
  return [...(element.type === 'button' ? [element] : []), ...buttons(element.props?.children)];
}
test('local pages without a count use hasMore and never invent totals or page counts', async () => {
  const scope = { ...initialScope, authority: 'local' };
  const calls = [];
  const controller = createProjectMemoriesController({
    authority: 'local', initialScope: scope,
    client: { async load(current, options) {
      calls.push(options.page);
      return { ...snapshot(current, options.page), authority: 'local', total: null,
        hasMore: options.page === 1 };
    } },
  });
  await controller.load(scope);
  assert.equal(controller.getSnapshot().total, null);
  assert.deepEqual(controller.getSnapshot().pagination, { page: 1, pages: null, hasMore: true });
  await controller.goToPage(3);
  assert.deepEqual(calls, [1]);
  const Page = pageComponent();
  const controls = () => buttons(Page({ model: controller.getSnapshot(),
    onRetry() {}, onPageChange: controller.goToPage }));
  assert.equal(controls()[1].props.disabled, false);
  await controls()[1].props.onClick();
  assert.equal(controls()[1].props.disabled, true);
  await controller.goToPage(3);
  await controls()[0].props.onClick();
  assert.deepEqual(calls, [1, 2, 1]);
});
test('actual memory page buttons load next and previous pages and enforce bounds', async () => {
  const calls = [];
  const controller = createProjectMemoriesController({
    authority: 'cloud',
    initialScope,
    client: {
      async load(scope, options) {
        calls.push(options);
        return snapshot(scope, options.page);
      },
    },
  });
  const Page = pageComponent();
  const controls = () =>
    buttons(
      Page({
        model: controller.getSnapshot(),
        onRetry: controller.retry,
        onPageChange: controller.goToPage,
      }),
    );
  await controller.load(initialScope);
  assert.equal(controls()[0].props.disabled, true);
  assert.equal(controls()[1].props.disabled, false);
  await controls()[1].props.onClick();
  assert.equal(controller.getSnapshot().pagination.page, 2);
  await controls()[1].props.onClick();
  assert.equal(controller.getSnapshot().pagination.page, 3);
  assert.equal(controls()[1].props.disabled, true);
  await controller.goToPage(4);
  await controller.goToPage(0);
  await controls()[0].props.onClick();
  assert.deepEqual(
    calls.map(({ page, pageSize }) => [page, pageSize]),
    [
      [1, 50],
      [2, 50],
      [3, 50],
      [2, 50],
    ],
  );
  assert.equal(controller.getSnapshot().items[0].title, 'Page 2');
});
test('scope replacement resets pagination and ignores aborted old page completion', async () => {
  let resolveOld;
  let oldSignal;
  const calls = [];
  const controller = createProjectMemoriesController({
    authority: 'cloud',
    initialScope,
    client: {
      load(scope, options) {
        calls.push([scope.projectId, options.page]);
        if (scope.projectId === initialScope.projectId && options.page === 2) {
          oldSignal = options.signal;
          return new Promise((resolve) => {
            resolveOld = resolve;
          });
        }
        return Promise.resolve(snapshot(scope, options.page));
      },
    },
  });
  await controller.load(initialScope);
  const old = controller.goToPage(2);
  await controller.load({ ...initialScope, projectId: 'project-2' });
  assert.equal(oldSignal.aborted, true);
  resolveOld(snapshot(initialScope, 2));
  await old;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  assert.equal(controller.getSnapshot().pagination.page, 1);
  assert.deepEqual(calls, [
    ['project-1', 1],
    ['project-1', 2],
    ['project-2', 1],
  ]);
});
test('failed page retry retains requested page; cancellation cannot publish a late result', async () => {
  let fail = true;
  let complete;
  const calls = [];
  const controller = createProjectMemoriesController({
    authority: 'cloud',
    initialScope,
    client: {
      async load(scope, options) {
        calls.push(options.page);
        if (options.page === 2 && fail) {
          fail = false;
          throw Object.assign(new Error('unavailable'), { status: 503 });
        }
        if (options.page === 3)
          return new Promise((resolve) => {
            complete = resolve;
          });
        return snapshot(scope, options.page);
      },
    },
  });
  await controller.load(initialScope);
  await controller.goToPage(2);
  assert.equal(controller.getSnapshot().retryVisible, true);
  assert.equal(controller.getSnapshot().pagination, undefined);
  await controller.retry();
  assert.equal(controller.getSnapshot().pagination.page, 2);
  assert.deepEqual(calls, [1, 2, 2]);
  const pending = controller.goToPage(3);
  controller.stop();
  complete(snapshot(initialScope, 3));
  await pending;
  assert.equal(controller.getSnapshot().state, 'loading');
  assert.equal(controller.getSnapshot().items.length, 0);
});
test('empty memory page has bounded controls and other knowledge routes omit pagination', async () => {
  const controller = createProjectMemoriesController({
    authority: 'cloud',
    initialScope,
    client: {
      async load(scope) {
        return { ...snapshot(scope, 1, 0), memories: [] };
      },
    },
  });
  await controller.load(initialScope);
  const Page = pageComponent();
  const model = controller.getSnapshot();
  assert.deepEqual(model.pagination, { page: 1, pages: 1 });
  assert.ok(
    buttons(Page({ model, onRetry() {}, onPageChange: controller.goToPage })).every(
      ({ props }) => props.disabled,
    ),
  );
  const { pagination, ...otherModel } = model;
  assert.equal(
    buttons(Page({ model: { ...otherModel, routeId: 'project-project-entities' }, onRetry() {} }))
      .length,
    0,
  );
});

test('previous page recovers when concurrent deletion shrinks the result below the current page', async () => {
  const pages = [];
  const controller = createProjectMemoriesController({
    authority: 'cloud', initialScope,
    client: { async load(scope, options) {
      pages.push(options.page);
      return { ...snapshot(scope, options.page, options.page === 3 ? 0 : 101), memories: [] };
    } },
  });
  await controller.load(initialScope);
  await controller.goToPage(3);
  assert.deepEqual(controller.getSnapshot().pagination, { page: 3, pages: 1 });
  await controller.goToPage(2);
  assert.deepEqual(pages, [1, 3, 1]);
});
