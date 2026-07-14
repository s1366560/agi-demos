import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  SETTINGS_GROUPS,
  filterSettingsSections,
  projectsForTenant,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/settingsNavigationModel.js');

const labels = {
  account: ['Account', 'Identity and sign-in'],
  workspace: ['Workspace', 'Tenant and project context'],
  general: ['General', 'Language and region'],
  appearance: ['Appearance', 'Theme and density'],
  notifications: ['Notifications', 'Review alerts'],
  models: ['Models', 'Providers and routing'],
  skills: ['Skills', 'Reusable instructions'],
  plugins: ['Plugins', 'External capabilities'],
  agents: ['Agents', 'Roles and autonomy'],
};

test('settings information architecture matches the approved prototype order', () => {
  assert.deepEqual(SETTINGS_GROUPS, [
    { id: 'account_context', sections: ['account', 'workspace'] },
    { id: 'preferences', sections: ['general', 'appearance', 'notifications'] },
    { id: 'ai_resources', sections: ['models', 'skills', 'plugins', 'agents'] },
  ]);
});

test('settings search only matches localized section labels and descriptions', () => {
  assert.deepEqual(filterSettingsSections('routing', labels), ['models']);
  assert.deepEqual(filterSettingsSections('review', labels), ['notifications']);
  assert.deepEqual(filterSettingsSections('workspace', labels), ['workspace']);
  assert.deepEqual(filterSettingsSections('missing', labels), []);
});

test('empty settings search preserves the full section order', () => {
  assert.deepEqual(filterSettingsSections('', labels), [
    'account',
    'workspace',
    'general',
    'appearance',
    'notifications',
    'models',
    'skills',
    'plugins',
    'agents',
  ]);
});

test('workspace project choices fail closed to the selected tenant scope', () => {
  const projects = [
    { id: 'p-a', tenant_id: 'tenant-a', name: 'A' },
    { id: 'p-b', tenant_id: 'tenant-b', name: 'B' },
    { id: 'p-missing', tenant_id: '', name: 'Missing scope' },
  ];
  assert.deepEqual(projectsForTenant(projects, 'tenant-a'), [projects[0]]);
  assert.deepEqual(projectsForTenant(projects, ''), []);
});
