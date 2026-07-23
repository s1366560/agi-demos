import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const panelSource = await readFile(
  new URL('../src/features/workspace/WorkspaceAgentBindingsPanel.tsx', import.meta.url),
  'utf8',
);
const dialogSource = await readFile(
  new URL('../src/features/workspace/WorkspaceSettingsDialog.tsx', import.meta.url),
  'utf8',
);
const appSource = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('workspace settings owns a separate authoritative Agent-binding panel', () => {
  assert.match(dialogSource, /<WorkspaceAgentBindingsPanel/);
  assert.match(dialogSource, /agents=\{agents\}/);
  assert.match(dialogSource, /members=\{members\}/);
  assert.match(appSource, /agents=\{dataset\.workspaceAgents\}/);
  assert.match(appSource, /onLoadAgentDefinitions=\{loadWorkspaceAgentDefinitionsFromDialog\}/);
  assert.match(appSource, /onBindAgent=\{bindWorkspaceAgentFromDialog\}/);
  assert.match(appSource, /onUnbindAgent=\{unbindWorkspaceAgentFromDialog\}/);
});

test('workspace Agent controls preserve authority, binding identity, confirmation, and feedback', () => {
  assert.match(panelSource, /canManageWorkspaceAgentBindings/);
  assert.match(panelSource, /agents\.status === 'loading'/);
  assert.match(panelSource, /agents\.status === 'error'/);
  assert.match(panelSource, /agents\.status === 'unavailable'/);
  assert.match(panelSource, /availableWorkspaceAgentDefinitions/);
  assert.match(panelSource, /binding\.is_active/);
  assert.match(panelSource, /onBindAgent\(\s*selectedAgentId/);
  assert.match(panelSource, /onUnbindAgent\(\s*binding\.id/);
  assert.doesNotMatch(panelSource, /onUnbindAgent\(\s*binding\.agent_id/);
  assert.match(panelSource, /<AlertDialog\.Root/);
  assert.match(panelSource, /aria-live=/);
  assert.match(panelSource, /WorkspaceSettingsScopeChangedError/);
});
