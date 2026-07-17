import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { AuxiliaryView } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/AuxiliaryView.js'
);

function renderAuxiliary(metricStatus, overrides = {}) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(AuxiliaryView, {
        section: 'home',
        userName: 'Alex',
        runningCount: 3,
        needsInputCount: 2,
        readyCount: 4,
        metricStatus,
        onOpenMyWork: () => {},
        onRetryMyWork: () => {},
        ...overrides,
      }),
    ),
  );
}

test('ready metrics render authoritative counts without adding a nested main landmark', () => {
  const markup = renderAuxiliary('ready');

  assert.match(markup, /^<section class="auxiliary-view"/);
  assert.doesNotMatch(markup, /<main/);
  assert.match(markup, /aria-busy="false"/);
  assert.match(markup, /<b>3<\/b>/);
  assert.match(markup, /<b>2<\/b>/);
  assert.match(markup, /<b>4<\/b>/);
});

test('loading metrics stay unknown until the authoritative queue resolves', () => {
  const markup = renderAuxiliary('loading', {
    runningCount: 0,
    needsInputCount: 0,
    readyCount: 0,
  });

  assert.match(markup, /aria-busy="true"/);
  assert.equal((markup.match(/<b>—<\/b>/g) ?? []).length, 3);
  assert.match(markup, /Loading authoritative task status/);
  assert.doesNotMatch(markup, /<b>0<\/b>/);
  assert.doesNotMatch(markup, /0 tasks are running/);
});

test('failed metrics expose a localized retry instead of presenting false zeroes', () => {
  const markup = renderAuxiliary('error', {
    runningCount: 0,
    needsInputCount: 0,
    readyCount: 0,
  });

  assert.match(markup, /role="alert"/);
  assert.equal((markup.match(/<b>—<\/b>/g) ?? []).length, 3);
  assert.match(markup, /Authoritative task status is unavailable/);
  assert.match(markup, />Retry task status<\/button>/);
  assert.doesNotMatch(markup, /<b>0<\/b>/);
  assert.doesNotMatch(markup, /0 tasks are running/);
});
