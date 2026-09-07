import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { AutomationRecoveryNotice } = require('/tmp/agistack-desktop-test-dist/src/features/automations/AutomationRecoveryNotice.js');
const { automationLocalRecovery } = require('/tmp/agistack-desktop-test-dist/src/features/automations/automationModel.js');

function markup(state, props = {}) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null,
    React.createElement(AutomationRecoveryNotice, {
      job: { state }, runAllowed: true, busy: false, onRun() {}, ...props,
    }),
  ));
}

test('recovery requires explicit local authority and a valid persisted count', () => {
  for (const state of [
    {}, { missed_run_count: 3 }, { execution_target: 'cloud', missed_run_count: 3 },
    ...[-1, 1.5, '3', Number.MAX_SAFE_INTEGER + 1].map((count) => ({ execution_target: 'local', missed_run_count: count })),
  ]) {
    assert.equal(automationLocalRecovery({ state }), null);
    assert.equal(markup(state), '');
  }
  assert.deepEqual(automationLocalRecovery({ state: { execution_target: 'local', missed_run_count: 3 } }), { missedRunCount: 3 });
});

test('catch-up action retains runtime permission and busy gates', () => {
  const state = { execution_target: 'local', missed_run_count: 3 };
  assert.match(markup(state), /3/);
  assert.match(markup(state), /<button[^>]*>/);
  assert.doesNotMatch(markup(state), /<button[^>]*disabled/);
  assert.match(markup(state, { runAllowed: false }), /<button[^>]*disabled/);
  assert.match(markup(state, { busy: true }), /<button[^>]*disabled/);
  assert.doesNotMatch(markup({ ...state, missed_run_count: 0 }), /<button/);
});
