import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { settingsSectionForEntry } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/settingsEntryRouting.js'
);

test('sidebar Settings and Account settings open the account section', () => {
  assert.equal(settingsSectionForEntry('sidebar'), 'account');
});

test('Workspace Overview Configure opens workspace settings', () => {
  assert.equal(settingsSectionForEntry('workspace_overview'), 'workspace');
});

test('explicit runtime connection actions open connection settings', () => {
  assert.equal(settingsSectionForEntry('runtime_connection'), 'connection');
});
