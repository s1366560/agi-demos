import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { latestAgentDefinitionEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/agentDefinitionEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const settingsSource = readFileSync(
  new URL('../src/features/settings/SettingsWindow.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/ProviderSettingsQa.tsx', import.meta.url), 'utf8');

test('latest Agent definition event follows the newest-first socket contract', () => {
  const newest = {
    type: 'agent_definition_updated',
    data: { agent_id: 'agent-reviewer', agent_name: 'review_guardian' },
  };
  const older = {
    event_type: 'agent_definition_created',
    payload: { agent_id: 'agent-atlas', agent_name: 'atlas' },
  };

  assert.equal(
    latestAgentDefinitionEvent([
      { type: 'heartbeat' },
      newest,
      { type: 'toolset_changed' },
      older,
    ]),
    newest,
  );
  assert.equal(latestAgentDefinitionEvent([older]), older);
  assert.equal(latestAgentDefinitionEvent([{ type: 'agent_spawned' }]), null);
});

test('Desktop forwards Agent definition events into the active settings resource snapshot', () => {
  assert.match(appSource, /latestAgentDefinitionEvent\(socket\.events\)/);
  assert.match(appSource, /agentDefinitionEvent=\{agentDefinitionEvent\}/);
  assert.match(settingsSource, /agentDefinitionEvent: AgentWsEvent \| null/);
  assert.match(settingsSource, /agentDefinitionEventRef/);
  assert.match(settingsSource, /activeSectionRef\.current !== 'agents'/);
  assert.match(settingsSource, /void loadResources\('agents'\)/);
});

test('Agent settings QA can publish a server-shaped definition event after initial load', () => {
  assert.match(qaSource, /agent-definition-event/);
  assert.match(qaSource, /agent_definition_created/);
  assert.match(qaSource, /setAgentDefinitionEvent/);
  assert.match(qaSource, /agentDefinitionEvent=\{agentDefinitionEvent\}/);
});
