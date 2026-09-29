import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const module = { exports: {} };
const source = readFileSync(
  new URL('../src/features/session/SessionContextRail.tsx', import.meta.url),
  'utf8',
);
const code = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;
new Function('require', 'module', 'exports', code)(
  (name) => {
    if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
    if (name === './SessionWorkspace') {
      return { statusLabel: (value) => value, executionModeLabel: (value) => value };
    }
    if (name.endsWith('.css')) return {};
    return require(name);
  },
  module,
  module.exports,
);
const { SessionContextRail } = module.exports;
const empty = {
  status: 'unavailable',
  stage: 'unavailable',
  executionMode: 'unavailable',
  environmentLabel: null,
  elapsedLabel: null,
  permissionLabel: null,
  observedToolActivityCount: 0,
  observedFailedToolActivityCount: 0,
  sourceCount: 0,
  error: null,
};
const render = (values = {}) => renderToStaticMarkup(
  React.createElement(SessionContextRail, { viewModel: { ...empty, ...values } }),
);

test('run details show one empty message instead of unavailable rows and zero statistics', () => {
  const markup = render();
  assert.match(markup, /session.dataUnavailableTitle/);
  assert.doesNotMatch(markup, /<dl|<dt|session.notAvailable|session.loadedToolActivity/);
});

test('run details retain supplied metadata without snapshot cards or review actions', () => {
  const markup = render({
    status: 'ready_review',
    stage: 'review',
    environmentLabel: '/workspace/project',
    elapsedLabel: '42s',
    observedToolActivityCount: 3,
    runActions: ['approve', 'request_changes'],
  });
  assert.match(markup, /\/workspace\/project/);
  assert.match(markup, /42s/);
  assert.match(markup, /session.loadedToolActivity<\/dt><dd>3/);
  assert.doesNotMatch(markup, /<button|<form|progress|runSnapshot|workSurfaces|loadedFailedToolActivity/);
});

test('run details preserve actual errors even without run metadata', () => {
  const markup = render({ error: 'Provider rejected the request <reason>' });
  assert.match(markup, /role="alert"/);
  assert.match(markup, /Provider rejected the request &lt;reason&gt;/);
  assert.doesNotMatch(markup, /session.dataUnavailableTitle/);
});
