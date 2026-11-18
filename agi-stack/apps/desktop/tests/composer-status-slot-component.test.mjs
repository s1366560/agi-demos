import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents: "export {ComposerStatusSlot} from './src/features/chat/ComposerStatusSlot'; export {I18nProvider} from './src/i18n';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false, bundle: true, platform: 'node', format: 'cjs', packages: 'external',
  loader: { '.css': 'empty' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports);
const { ComposerStatusSlot, I18nProvider } = module.exports;
const render = (props) => renderToStaticMarkup(React.createElement(I18nProvider, null,
  React.createElement(ComposerStatusSlot, props)));
const notice = { tone: 'loading', title: 'Restoring session', description: 'Synchronizing run state; messages stay readable.' };

test('the transient status region remains mounted when idle', () => {
  const idle = render({ queueLoading: false });
  assert.match(idle, /class="composer-status-slot"/);
  assert.match(idle, /role="status" aria-live="polite" aria-atomic="true"/);
  assert.doesNotMatch(idle, /composer-status-recovery|composer-status-queue/);
});

test('recovery text and queue synchronization share a compact region', () => {
  const html = render({ notice, queueLoading: true });
  assert.match(html, /Restoring session/);
  assert.match(html, /Synchronizing run state; messages stay readable\./);
  assert.match(html, /title="Restoring session Synchronizing run state; messages stay readable\."/);
  assert.match(html, /composer-status-queue/);
  assert.doesNotMatch(html, /<button|<section/);
});

test('warnings, failures and actionable recovery stay outside the compact region', () => {
  for (const fullNotice of [{ ...notice, tone: 'error' }, { ...notice, tone: 'warning' },
    { ...notice, actionLabel: 'Retry' }]) {
    assert.doesNotMatch(render({ notice: fullNotice, queueLoading: false }), /Restoring session/);
  }
});
