import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { ExecutionTargetBadge, ExecutionTargetFilterBar, executionTargetOf } = require(
  `${root}/features/session/ExecutionTargetBadge.js`,
);

const render = (element) =>
  renderToStaticMarkup(React.createElement(I18nProvider, null, element));

test('missing execution target renders the cloud badge and default environment', () => {
  assert.equal(executionTargetOf(undefined), 'cloud');
  const html = render(React.createElement(ExecutionTargetBadge, {}));
  assert.match(html, /Cloud|云端/);
  assert.match(html, /Default environment|默认环境/);
  assert.match(html, /data-execution-target="cloud"/);
});

test('local runs show this computer and the directory label', () => {
  const html = render(
    React.createElement(ExecutionTargetBadge, {
      executionTarget: 'local',
      localRootLabel: 'agi-demos',
      running: true,
    }),
  );
  assert.match(html, /This computer|此计算机/);
  assert.match(html, /agi-demos/);
  assert.match(html, /data-running="true"/);
});

test('filter exposes all, this computer, and cloud without a local create control', () => {
  const html = render(
    React.createElement(ExecutionTargetFilterBar, {
      value: 'all',
      onChange: () => undefined,
    }),
  );
  assert.match(html, /All|全部/);
  assert.match(html, /This computer|此计算机/);
  assert.match(html, /Cloud|云端/);
  assert.equal(html.includes('New task'), false);
  assert.equal(html.includes('新建'), false);
});
