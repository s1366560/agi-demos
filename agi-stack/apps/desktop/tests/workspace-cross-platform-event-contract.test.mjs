import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

// Single source of truth shared with the web client contract test
// (web/src/test/stores/workspaceEventContract.test.ts). Both ends assert
// against the same fixture so a single-sided event type addition, rename, or
// removal fails the contract test on at least one end.
const CONTRACT_FIXTURE_PATH = '../../../../shared/fixtures/workspace-event-contract.v1.json';
const contract = JSON.parse(
  readFileSync(new URL(CONTRACT_FIXTURE_PATH, import.meta.url), 'utf8'),
);

const {
  applyWorkspaceMessageStreamEvent,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/workspaceMessageEventModel.js');
const {
  applyWorkspaceRosterStreamEvent,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/workspaceRosterEventModel.js');
const {
  applyWorkspaceTaskStreamEvent,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/workspaceTaskEventModel.js');
const {
  applyWorkspaceLifecycleStreamEvent,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/workspaceLifecycleEventModel.js');

// Event model sources whose quoted event-type vocabulary must match the
// contract fixture. These are the desktop-side consumers of the shared
// workspace WebSocket event stream.
const EVENT_MODEL_SOURCES = [
  '../src/features/chat/workspaceMessageEventModel.ts',
  '../src/features/chat/workspaceRosterEventModel.ts',
  '../src/features/chat/workspaceTaskEventModel.ts',
  '../src/features/chat/workspaceLifecycleEventModel.ts',
];

// Quoted strings that are payload property names, not event types.
const PROPERTY_NAME_STRINGS = new Set(['workspace_id', 'workspace_agent_id']);

// Matches snake_case event type literals like workspace_task_created or
// workspace_deleted. Trailing-underscore prefix literals (for example
// 'workspace_task_') do not match, which keeps prefix dispatch strings out.
const EVENT_TYPE_PATTERN = /^workspace_(?:message|task|member|agent)_[a-z][a-z_]*$|^workspace_(?:updated|deleted)$/;

const EXPECTED_EVENT_TYPES = [
  'workspace_message_created',
  'workspace_task_created',
  'workspace_task_updated',
  'workspace_task_deleted',
  'workspace_task_status_changed',
  'workspace_task_assigned',
  'workspace_member_joined',
  'workspace_member_updated',
  'workspace_member_left',
  'workspace_agent_bound',
  'workspace_agent_unbound',
  'workspace_updated',
  'workspace_deleted',
];

function contractEventTypes() {
  const families = Object.values(contract.families);
  const types = families.flatMap((family) => family.event_types);
  assert.equal(new Set(types).size, types.length, 'fixture families must not overlap');
  return types;
}

function scannedEventTypes() {
  const scanned = new Set();
  for (const sourcePath of EVENT_MODEL_SOURCES) {
    const source = readFileSync(new URL(sourcePath, import.meta.url), 'utf8');
    for (const match of source.matchAll(/'([^']+)'/g)) {
      const literal = match[1];
      if (EVENT_TYPE_PATTERN.test(literal) && !PROPERTY_NAME_STRINGS.has(literal)) {
        scanned.add(literal);
      }
    }
  }
  return [...scanned].sort();
}

test('contract fixture is internally consistent', () => {
  const familyTypes = contractEventTypes();
  const sampleTypes = Object.keys(contract.sample_events).sort();
  assert.deepEqual(familyTypes.slice().sort(), EXPECTED_EVENT_TYPES.slice().sort());
  assert.deepEqual(sampleTypes, EXPECTED_EVENT_TYPES.slice().sort());
  assert.equal(contract.schema_version, '1.0.0');
});

test('desktop event model vocabulary matches the cross-platform contract exactly', () => {
  assert.deepEqual(scannedEventTypes(), EXPECTED_EVENT_TYPES.slice().sort());
});

test('desktop event models handle every contract sample event', () => {
  const { workspace_id: workspaceId, tenant_id: tenantId, project_id: projectId } =
    contract.shared_context;
  const samples = contract.sample_events;
  const emptyCollection = () => ({ status: 'available', items: [], error: null });

  // message family
  const messageResult = applyWorkspaceMessageStreamEvent(
    [],
    samples.workspace_message_created,
    workspaceId,
  );
  assert.equal(messageResult.handled, true, 'workspace_message_created must be handled');
  assert.equal(messageResult.messages.length, 1);

  // task family: created -> updated -> status_changed -> assigned -> deleted
  let tasks = [];
  let created = applyWorkspaceTaskStreamEvent(tasks, samples.workspace_task_created, workspaceId);
  assert.equal(created.handled, true, 'workspace_task_created must be handled');
  tasks = created.tasks;
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].title, 'contract fixture task');

  let updated = applyWorkspaceTaskStreamEvent(tasks, samples.workspace_task_updated, workspaceId);
  assert.equal(updated.handled, true, 'workspace_task_updated must be handled');
  tasks = updated.tasks;
  assert.equal(tasks[0].title, 'contract fixture task v2');

  let statusChanged = applyWorkspaceTaskStreamEvent(
    tasks,
    samples.workspace_task_status_changed,
    workspaceId,
  );
  assert.equal(statusChanged.handled, true, 'workspace_task_status_changed must be handled');
  tasks = statusChanged.tasks;
  assert.equal(tasks[0].status, 'in_progress');

  let assigned = applyWorkspaceTaskStreamEvent(tasks, samples.workspace_task_assigned, workspaceId);
  assert.equal(assigned.handled, true, 'workspace_task_assigned must be handled');
  tasks = assigned.tasks;
  assert.equal(tasks[0].workspace_agent_id, 'wag-contract-1');

  let deleted = applyWorkspaceTaskStreamEvent(tasks, samples.workspace_task_deleted, workspaceId);
  assert.equal(deleted.handled, true, 'workspace_task_deleted must be handled');
  assert.equal(deleted.tasks.length, 0);

  // member + agent binding families
  let members = emptyCollection();
  let agents = emptyCollection();
  let joined = applyWorkspaceRosterStreamEvent(
    members,
    agents,
    samples.workspace_member_joined,
    workspaceId,
  );
  assert.equal(joined.handled, true, 'workspace_member_joined must be handled');
  members = joined.members;
  assert.equal(members.items.length, 1);
  assert.equal(members.items[0].role, 'member');

  let memberUpdated = applyWorkspaceRosterStreamEvent(
    members,
    agents,
    samples.workspace_member_updated,
    workspaceId,
  );
  assert.equal(memberUpdated.handled, true, 'workspace_member_updated must be handled');
  members = memberUpdated.members;
  assert.equal(members.items[0].role, 'editor');

  let left = applyWorkspaceRosterStreamEvent(
    members,
    agents,
    samples.workspace_member_left,
    workspaceId,
  );
  assert.equal(left.handled, true, 'workspace_member_left must be handled');
  members = left.members;
  assert.equal(members.items.length, 0);

  let bound = applyWorkspaceRosterStreamEvent(
    members,
    agents,
    samples.workspace_agent_bound,
    workspaceId,
  );
  assert.equal(bound.handled, true, 'workspace_agent_bound must be handled');
  agents = bound.agents;
  assert.equal(agents.items.length, 1);

  let unbound = applyWorkspaceRosterStreamEvent(
    members,
    agents,
    samples.workspace_agent_unbound,
    workspaceId,
  );
  assert.equal(unbound.handled, true, 'workspace_agent_unbound must be handled');
  assert.equal(unbound.agents.items.length, 0);

  // lifecycle family
  const workspace = samples.workspace_updated.data.workspace;
  const dataset = {
    workspaces: [workspace],
    workspacesByProject: { [projectId]: [workspace] },
    conversationsByWorkspace: {},
    nodeState: { workspaces: {} },
    messages: [],
    tasks: [],
    plan: null,
    workspaceMembers: emptyCollection(),
    workspaceAgents: emptyCollection(),
    sandbox: null,
    myWork: [],
    myWorkError: null,
  };
  let lifecycleUpdated = applyWorkspaceLifecycleStreamEvent(dataset, samples.workspace_updated, {
    tenantId,
    projectId,
    workspaceId,
  });
  assert.equal(lifecycleUpdated.handled, true, 'workspace_updated must be handled');
  assert.equal(lifecycleUpdated.dataset.workspaces[0].name, 'Contract Fixture Workspace');

  let lifecycleDeleted = applyWorkspaceLifecycleStreamEvent(
    lifecycleUpdated.dataset,
    samples.workspace_deleted,
    { tenantId, projectId, workspaceId },
  );
  assert.equal(lifecycleDeleted.handled, true, 'workspace_deleted must be handled');
  assert.equal(lifecycleDeleted.dataset.workspaces.length, 0);
  assert.equal(lifecycleDeleted.activeWorkspaceDeleted, true);
});

test('desktop event models ignore event types outside the contract', () => {
  const { workspace_id: workspaceId } = contract.shared_context;
  const unknownEvent = {
    type: 'workspace_message_renamed',
    data: { workspace_id: workspaceId },
  };
  assert.equal(
    applyWorkspaceMessageStreamEvent([], unknownEvent, workspaceId).handled,
    false,
    'unknown message event types must not be handled',
  );
  assert.equal(
    applyWorkspaceTaskStreamEvent([], unknownEvent, workspaceId).handled,
    false,
    'unknown task event types must not be handled',
  );
});
