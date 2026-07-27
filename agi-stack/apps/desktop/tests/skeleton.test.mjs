import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider, useI18n } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { Skeleton, SkeletonGroup } = require(
  '/tmp/agistack-desktop-test-dist/src/components/Skeleton.js'
);
const skeletonModel = require('/tmp/agistack-desktop-test-dist/src/components/skeletonModel.js');

const skeletonSource = readFileSync(
  new URL('../src/components/Skeleton.tsx', import.meta.url),
  'utf8',
);
const skeletonCssSource = readFileSync(
  new URL('../src/components/Skeleton.css', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const workspaceDockSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceDock.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function withStoredLocale(locale, render) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => (key === 'agistack.desktop.locale' ? locale : null),
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return render();
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
}

function renderLocalizedGroup(labelKey) {
  function Harness() {
    const { t } = useI18n();
    return React.createElement(
      SkeletonGroup,
      { label: t(labelKey) },
      React.createElement(Skeleton, { variant: 'text', width: '58%' })
    );
  }
  return renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Harness)));
}

test('messageSkeletonRows are deterministic and cycle bar patterns', () => {
  const first = skeletonModel.messageSkeletonRows(3);
  const second = skeletonModel.messageSkeletonRows(3);
  assert.deepEqual(first, second);
  assert.equal(first.length, 3);
  assert.deepEqual(first.map((row) => row.id), [
    'skeleton-message-0',
    'skeleton-message-1',
    'skeleton-message-2',
  ]);
  for (const row of first) {
    assert.ok(row.barWidths.length >= 2);
    for (const width of row.barWidths) assert.match(width, /%$/);
  }
  const wrapped = skeletonModel.messageSkeletonRows(4);
  assert.deepEqual(wrapped[3].barWidths, wrapped[0].barWidths);
  assert.deepEqual(skeletonModel.messageSkeletonRows(0), []);
});

test('treeSkeletonRows indent children under the first row', () => {
  const rows = skeletonModel.treeSkeletonRows(4);
  assert.equal(rows.length, 4);
  assert.equal(rows[0].depth, 0);
  assert.ok(rows.slice(1).every((row) => row.depth === 1));
  for (const row of rows) assert.match(row.width, /%$/);
  assert.deepEqual(skeletonModel.treeSkeletonRows(0), []);
});

test('Skeleton renders an aria-hidden placeholder per variant', () => {
  const text = renderToStaticMarkup(React.createElement(Skeleton));
  assert.match(text, /aria-hidden="true"/);
  assert.match(text, /class="skeleton skeleton-text"/);
  assert.doesNotMatch(text, />[^<]+</);

  const circle = renderToStaticMarkup(
    React.createElement(Skeleton, { variant: 'circle', width: 32, height: 32 })
  );
  assert.match(circle, /class="skeleton skeleton-circle"/);
  assert.match(circle, /style="width:32px;height:32px"/);

  const rect = renderToStaticMarkup(
    React.createElement(Skeleton, { variant: 'rect', width: '50%', className: 'extra' })
  );
  assert.match(rect, /class="skeleton skeleton-rect extra"/);
  assert.match(rect, /style="width:50%"/);
});

test('SkeletonGroup announces one localized status region in en', () => {
  const markup = withStoredLocale('en', () => renderLocalizedGroup('session.loadingHistory'));
  assert.match(markup, /role="status"/);
  assert.match(markup, /aria-label="Loading session history…"/);
  assert.match(markup, /<span class="sr-only">Loading session history…<\/span>/);
  assert.equal((markup.match(/role="status"/g) ?? []).length, 1);
  assert.match(markup, /aria-hidden="true"/);
});

test('SkeletonGroup announces one localized status region in zh-CN', () => {
  const markup = withStoredLocale('zh-CN', () => renderLocalizedGroup('session.loadingHistory'));
  assert.match(markup, /aria-label="正在加载会话历史…"/);
  assert.match(markup, /<span class="sr-only">正在加载会话历史…<\/span>/);
});

test('skeleton labels rely on i18n keys present in both dictionaries', () => {
  for (const key of [
    'session.loadingHistory',
    'session.loadingEarlierHistory',
    'workspaceTree.loading',
    'workspaceTree.loadingTasks',
    'workspaceTree.loadingSessions',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
    );
  }
});

test('Skeleton source keeps user-visible strings out of the component', () => {
  assert.doesNotMatch(skeletonSource, /aria-label="[A-Za-z]/);
  assert.doesNotMatch(skeletonSource, /placeholder="[A-Za-z]/);
  assert.doesNotMatch(skeletonSource, />[A-Z][a-z]+ [a-z]+</);
});

test('Skeleton styles use desktop tokens and honor reduced motion', () => {
  assert.match(skeletonCssSource, /var\(--desktop-panel-2\)/);
  assert.match(skeletonCssSource, /var\(--desktop-border\)/);
  assert.match(skeletonCssSource, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(skeletonCssSource, /@keyframes skeleton-shimmer/);
  assert.doesNotMatch(skeletonCssSource, /#[0-9a-fA-F]{3,8}\b/);
});

test('chat timeline loading states render grouped skeletons', () => {
  assert.match(chatTimelineSource, /SkeletonGroup[\s\S]*session\.loadingHistory/);
  assert.match(chatTimelineSource, /SkeletonGroup[\s\S]*session\.loadingEarlierHistory/);
  assert.match(chatTimelineSource, /messageSkeletonRows\(3\)/);
  assert.doesNotMatch(chatTimelineSource, /timeline-skeleton-bar/);
});

test('workspace dock loading branches render grouped tree skeletons', () => {
  assert.match(workspaceDockSource, /WorkspaceTreeSkeleton label=\{t\('workspaceTree\.loading'\)\}/);
  assert.match(
    workspaceDockSource,
    /WorkspaceTreeSkeleton label=\{t\('workspaceTree\.loadingTasks'\)\}/
  );
  assert.match(
    workspaceDockSource,
    /WorkspaceTreeSkeleton[\s\S]*t\('workspaceTree\.loadingSessions'\)/
  );
});
