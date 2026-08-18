import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { useWorkspaceStore } from '@/stores/workspace';
import type { Workspace } from '@/types/workspace';

// Single source of truth shared with the desktop client contract test
// (agi-stack/apps/desktop/tests/workspace-cross-platform-event-contract.test.mjs).
// Both ends assert against the same fixture so a single-sided event type
// addition, rename, or removal fails the contract test on at least one end.
const FIXTURE_PATH = resolve(
  process.cwd(),
  '../shared/fixtures/workspace-event-contract.v1.json'
);

const contract = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8')) as {
  schema_version: string;
  shared_context: { workspace_id: string; tenant_id: string; project_id: string };
  families: Record<string, { event_types: string[] }>;
  sample_events: Record<string, { type: string; data: Record<string, unknown> }>;
};

// Web-side consumers of the shared workspace WebSocket event stream whose
// quoted event-type vocabulary must match the contract fixture: the zustand
// store handlers plus the socket hook that dispatches into them.
const CONSUMER_SOURCES = [
  resolve(process.cwd(), 'src/stores/workspace.ts'),
  resolve(process.cwd(), 'src/hooks/useWorkspaceWebSocket.ts'),
];

// Quoted strings that are payload property names, not event types.
const PROPERTY_NAME_STRINGS = new Set(['workspace_id', 'workspace_agent_id']);

// Matches snake_case event type literals like workspace_task_created or
// workspace_deleted. Trailing-underscore prefix literals (for example
// 'workspace_task_') and dotted namespaces (workspace.presence.*) do not
// match, which keeps dispatch prefixes and out-of-scope families out.
const EVENT_TYPE_PATTERN =
  /^workspace_(?:message|task|member|agent)_[a-z][a-z_]*$|^workspace_(?:updated|deleted)$/;

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

function contractEventTypes(): string[] {
  const types = Object.values(contract.families).flatMap((family) => family.event_types);
  expect(new Set(types).size).toBe(types.length);
  return types;
}

function scannedEventTypes(): string[] {
  const scanned = new Set<string>();
  for (const sourcePath of CONSUMER_SOURCES) {
    const source = readFileSync(sourcePath, 'utf8');
    for (const match of source.matchAll(/'([^']+)'/g)) {
      const literal = match[1];
      if (EVENT_TYPE_PATTERN.test(literal) && !PROPERTY_NAME_STRINGS.has(literal)) {
        scanned.add(literal);
      }
    }
  }
  return [...scanned].sort();
}

function resetWorkspaceStore(overrides: Partial<ReturnType<typeof useWorkspaceStore.getState>> = {}) {
  useWorkspaceStore.setState({
    tasks: [],
    members: [],
    agents: [],
    chatMessages: [],
    workspaces: [],
    currentWorkspace: null,
    ...overrides,
  });
}

describe('cross-platform workspace event contract fixture', () => {
  it('is internally consistent', () => {
    const familyTypes = contractEventTypes().sort();
    const sampleTypes = Object.keys(contract.sample_events).sort();
    expect(familyTypes).toEqual([...EXPECTED_EVENT_TYPES].sort());
    expect(sampleTypes).toEqual([...EXPECTED_EVENT_TYPES].sort());
    expect(contract.schema_version).toBe('1.0.0');
  });

  it('web consumer vocabulary matches the cross-platform contract exactly', () => {
    expect(scannedEventTypes()).toEqual([...EXPECTED_EVENT_TYPES].sort());
  });
});

describe('web workspace store handles every contract sample event', () => {
  beforeEach(() => {
    resetWorkspaceStore();
  });

  it('handles workspace_message_created', () => {
    const store = useWorkspaceStore.getState();
    store.handleChatEvent(contract.sample_events.workspace_message_created);
    const state = useWorkspaceStore.getState();
    expect(state.chatMessages).toHaveLength(1);
    expect(state.chatMessages[0]).toMatchObject({ id: 'msg-contract-1', content: 'contract fixture message' });
  });

  it('handles the task family end to end', () => {
    const store = useWorkspaceStore.getState();
    store.handleTaskEvent(contract.sample_events.workspace_task_created);
    expect(useWorkspaceStore.getState().tasks).toHaveLength(1);
    expect(useWorkspaceStore.getState().tasks[0]).toMatchObject({ id: 'task-contract-1', status: 'pending' });

    store.handleTaskEvent(contract.sample_events.workspace_task_updated);
    expect(useWorkspaceStore.getState().tasks[0]).toMatchObject({ title: 'contract fixture task v2' });

    store.handleTaskEvent(contract.sample_events.workspace_task_status_changed);
    expect(useWorkspaceStore.getState().tasks[0]).toMatchObject({ status: 'in_progress' });

    store.handleTaskEvent(contract.sample_events.workspace_task_assigned);
    expect(useWorkspaceStore.getState().tasks[0]).toMatchObject({ workspace_agent_id: 'wag-contract-1' });

    store.handleTaskEvent(contract.sample_events.workspace_task_deleted);
    expect(useWorkspaceStore.getState().tasks).toHaveLength(0);
  });

  it('handles the member family end to end', () => {
    const store = useWorkspaceStore.getState();
    store.handleMemberEvent(contract.sample_events.workspace_member_joined);
    expect(useWorkspaceStore.getState().members).toHaveLength(1);
    expect(useWorkspaceStore.getState().members[0]).toMatchObject({ role: 'member' });

    store.handleMemberEvent(contract.sample_events.workspace_member_updated);
    expect(useWorkspaceStore.getState().members[0]).toMatchObject({ role: 'editor' });

    store.handleMemberEvent(contract.sample_events.workspace_member_left);
    expect(useWorkspaceStore.getState().members).toHaveLength(0);
  });

  it('handles the agent binding family end to end', () => {
    const store = useWorkspaceStore.getState();
    store.handleAgentBindingEvent(contract.sample_events.workspace_agent_bound);
    expect(useWorkspaceStore.getState().agents).toHaveLength(1);
    expect(useWorkspaceStore.getState().agents[0]).toMatchObject({ id: 'wag-contract-1' });

    store.handleAgentBindingEvent(contract.sample_events.workspace_agent_unbound);
    expect(useWorkspaceStore.getState().agents).toHaveLength(0);
  });

  it('handles the workspace lifecycle family end to end', () => {
    const staleWorkspace: Workspace = {
      ...(contract.sample_events.workspace_updated.data.workspace as unknown as Workspace),
      name: 'Stale Name',
    };
    resetWorkspaceStore({ workspaces: [staleWorkspace] });

    const store = useWorkspaceStore.getState();
    store.handleWorkspaceLifecycleEvent(contract.sample_events.workspace_updated);
    expect(useWorkspaceStore.getState().workspaces[0].name).toBe('Contract Fixture Workspace');

    store.handleWorkspaceLifecycleEvent(contract.sample_events.workspace_deleted);
    expect(useWorkspaceStore.getState().workspaces).toHaveLength(0);
  });

  it('ignores event types outside the contract', () => {
    const store = useWorkspaceStore.getState();
    store.handleTaskEvent({
      type: 'workspace_message_renamed',
      data: { workspace_id: contract.shared_context.workspace_id },
    });
    expect(useWorkspaceStore.getState().tasks).toHaveLength(0);
  });
});
