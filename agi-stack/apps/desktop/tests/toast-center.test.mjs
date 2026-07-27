import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { ToastProvider, ToastViewport, useToast } = require(
  '/tmp/agistack-desktop-test-dist/src/features/feedback/ToastCenter.js'
);
const toastModel = require('/tmp/agistack-desktop-test-dist/src/features/feedback/toastModel.js');

const toastCenterSource = readFileSync(
  new URL('../src/features/feedback/ToastCenter.tsx', import.meta.url),
  'utf8',
);
const toastCssSource = readFileSync(
  new URL('../src/features/feedback/ToastCenter.css', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function sequentialOrdinal(start = 0) {
  let ordinal = start;
  return () => {
    ordinal += 1;
    return ordinal;
  };
}

function pushConversationToasts() {
  const nextId = toastModel.createToastIdFactory(sequentialOrdinal());
  let queue = [];
  queue = toastModel.enqueueToast(queue, {
    id: nextId(),
    kind: 'success',
    message: 'Conversation renamed',
  });
  queue = toastModel.enqueueToast(queue, {
    id: nextId(),
    kind: 'error',
    message: 'Could not rename conversation',
    detail: 'Network request failed',
  });
  return queue;
}

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

function renderHarness(toasts) {
  function Harness() {
    const { showToast, dismissToast } = useToast();
    assert.equal(typeof showToast, 'function');
    assert.equal(typeof dismissToast, 'function');
    return React.createElement(ToastViewport, { toasts, onDismiss: () => {} });
  }
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ToastProvider, null, React.createElement(Harness)),
    ),
  );
}

test('enqueueToast caps the visible queue at three toasts', () => {
  const nextId = toastModel.createToastIdFactory(sequentialOrdinal());
  let queue = [];
  for (const kind of ['success', 'info', 'error', 'success']) {
    queue = toastModel.enqueueToast(queue, { id: nextId(), kind, message: kind });
  }
  assert.equal(queue.length, toastModel.MAX_VISIBLE_TOASTS);
  assert.deepEqual(
    queue.map((toast) => toast.message),
    ['info', 'error', 'success'],
  );
  assert.equal(toastModel.MAX_VISIBLE_TOASTS, 3);
});

test('dismissToastFromQueue removes by id and keeps identity for unknown ids', () => {
  const toasts = pushConversationToasts();
  const remaining = toastModel.dismissToastFromQueue(toasts, toasts[0].id);
  assert.equal(remaining.length, 1);
  assert.equal(remaining[0].id, toasts[1].id);
  assert.equal(toastModel.dismissToastFromQueue(toasts, 'toast-missing'), toasts);
});

test('toast kinds map to stable durations and aria roles', () => {
  assert.equal(toastModel.TOAST_AUTO_DISMISS_MS.success, 5000);
  assert.equal(toastModel.TOAST_AUTO_DISMISS_MS.info, 5000);
  assert.equal(toastModel.TOAST_AUTO_DISMISS_MS.error, 8000);
  assert.equal(toastModel.toastDismissDelay('success'), 5000);
  assert.equal(toastModel.toastDismissDelay('info'), 5000);
  assert.equal(toastModel.toastDismissDelay('error'), 8000);
  assert.equal(toastModel.toastAriaRole('success'), 'status');
  assert.equal(toastModel.toastAriaRole('info'), 'status');
  assert.equal(toastModel.toastAriaRole('error'), 'alert');
});

test('toast id factory uses the injected ordinal source deterministically', () => {
  const nextId = toastModel.createToastIdFactory(sequentialOrdinal(80));
  assert.equal(nextId(), 'toast-29');
  assert.equal(nextId(), 'toast-2a');
  const constant = toastModel.createToastIdFactory(() => 7);
  assert.equal(constant(), 'toast-7');
});

test('toast viewport announces success and error toasts with localized chrome', () => {
  const markup = withStoredLocale('en', () => renderHarness(pushConversationToasts()));

  assert.match(markup, /aria-live="polite"/);
  assert.match(markup, /aria-live="assertive"/);
  assert.match(markup, /role="status"/);
  assert.match(markup, /role="alert"/);
  assert.match(markup, /aria-label="Notifications"/);
  assert.match(markup, /aria-label="Dismiss notification"/);
  assert.match(markup, /Conversation renamed/);
  assert.match(markup, /Could not rename conversation/);
  assert.match(markup, /Network request failed/);
  assert.match(markup, /<button type="button"/);
});

test('toast viewport renders localized zh-CN chrome when the locale is stored', () => {
  const markup = withStoredLocale('zh-CN', () => renderHarness(pushConversationToasts()));
  assert.match(markup, /aria-label="通知"/);
  assert.match(markup, /aria-label="关闭通知"/);
  assert.match(markup, /role="status"/);
  assert.match(markup, /role="alert"/);
});

test('useToast throws outside ToastProvider', () => {
  function BareConsumer() {
    useToast();
    return null;
  }
  assert.throws(
    () => renderToStaticMarkup(React.createElement(BareConsumer)),
    /useToast must be used inside ToastProvider/,
  );
});

test('toast copy is centralized in both i18n dictionaries', () => {
  for (const key of [
    'toast.viewportLabel',
    'toast.dismiss',
    'toast.conversationRenameSuccess',
    'toast.conversationRenameError',
    'toast.conversationDeleteSuccess',
    'toast.conversationDeleteError',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
    );
  }
});

test('ToastCenter source keeps user-visible strings behind t()', () => {
  assert.match(toastCenterSource, /t\('toast\.viewportLabel'\)/);
  assert.match(toastCenterSource, /t\('toast\.dismiss'\)/);
  assert.doesNotMatch(toastCenterSource, /aria-label="[A-Za-z]/);
  assert.doesNotMatch(toastCenterSource, /placeholder="[A-Za-z]/);
  assert.doesNotMatch(toastCenterSource, />[A-Z][a-z]+ [a-z]+</);
});

test('ToastCenter styles use desktop tokens and honor reduced motion', () => {
  for (const token of [
    '--desktop-panel-2',
    '--desktop-border',
    '--desktop-text',
    '--desktop-muted',
    '--desktop-green',
    '--desktop-red',
    '--desktop-cyan',
  ]) {
    assert.match(toastCssSource, new RegExp(`var\\(${token}\\)`));
  }
  assert.match(toastCssSource, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(toastCssSource, /#[0-9a-fA-F]{3,8}\b/);
});
