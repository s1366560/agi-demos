import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyWorkspaceActivityStreamEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceActivityEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const overviewSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceOverview.tsx', import.meta.url),
  'utf8',
);

test('blackboard post and reply events become newest-first workspace activities', () => {
  let activities = [];
  ({ activities } = applyWorkspaceActivityStreamEvent(activities, {
    type: 'blackboard_post_created',
    data: {
      surface_boundary: 'owned',
      authority_class: 'authoritative',
      post: {
        id: 'post-1',
        workspace_id: 'workspace-1',
        title: 'Release readiness',
        content: 'All cloud checks are green.',
      },
    },
  }, 'workspace-1'));
  ({ activities } = applyWorkspaceActivityStreamEvent(activities, {
    type: 'blackboard_reply_updated',
    data: {
      surface_boundary: 'owned',
      authority_class: 'authoritative',
      post_id: 'post-1',
      reply: {
        id: 'reply-1',
        post_id: 'post-1',
        workspace_id: 'workspace-1',
        content: 'Desktop verification attached.',
      },
    },
  }, 'workspace-1'));

  assert.deepEqual(activities.map(({ title }) => title), [
    'Desktop verification attached.',
    'Release readiness',
  ]);
  assert.equal(activities[0].detail, 'post-1');
  assert.equal(activities[1].detail, 'All cloud checks are green.');
});

test('blackboard file and topology events expose structured names without protocol labels', () => {
  let activities = [];
  ({ activities } = applyWorkspaceActivityStreamEvent(activities, {
    type: 'blackboard_file_updated',
    data: {
      workspace_id: 'workspace-1',
      surface_boundary: 'owned',
      authority_class: 'authoritative',
      file: {
        id: 'file-1',
        workspace_id: 'workspace-1',
        parent_path: '/evidence',
        name: 'desktop-report.md',
      },
    },
  }, 'workspace-1'));
  ({ activities } = applyWorkspaceActivityStreamEvent(activities, {
    type: 'topology_updated',
    data: {
      workspace_id: 'workspace-1',
      operation: 'node_created',
      node: { id: 'node-1', workspace_id: 'workspace-1', title: 'Release Agent' },
    },
  }, 'workspace-1'));

  assert.equal(activities[0].title, 'Release Agent');
  assert.equal(activities[0].detail, 'node_created');
  assert.equal(activities[1].title, 'desktop-report.md');
  assert.equal(activities[1].detail, '/evidence');
});

test('delete events retain stable entity identity for the workspace audit trail', () => {
  let activities = [];
  for (const event of [
    { type: 'blackboard_post_deleted', data: { post_id: 'post-1' } },
    { type: 'blackboard_reply_deleted', data: { reply_id: 'reply-1', post_id: 'post-1' } },
    { type: 'blackboard_file_deleted', data: { workspace_id: 'workspace-1', file_id: 'file-1' } },
    { type: 'blackboard_directory_deleted', data: {
      workspace_id: 'workspace-1', file_id: 'directory-1', is_directory: true,
    } },
    { type: 'topology_updated', data: {
      workspace_id: 'workspace-1', operation: 'edge_deleted', edge_id: 'edge-1',
    } },
  ]) {
    ({ activities } = applyWorkspaceActivityStreamEvent(activities, event, 'workspace-1'));
  }
  assert.deepEqual(activities.map(({ title }) => title), [
    'edge-1', 'directory-1', 'file-1', 'reply-1', 'post-1',
  ]);
});

test('workspace activities reject cross-scope, non-authoritative, and malformed payloads', () => {
  const activities = [];
  for (const event of [
    { type: 'topology_updated', data: {
      workspace_id: 'workspace-2', operation: 'node_deleted', node_id: 'node-2',
    } },
    { type: 'blackboard_post_created', data: {
      surface_boundary: 'hosted',
      authority_class: 'non-authoritative',
      post: { id: 'post-1', workspace_id: 'workspace-1', title: 'Wrong surface' },
    } },
    { type: 'blackboard_reply_created', data: {
      reply: { id: 'reply-1', workspace_id: 'workspace-1' },
    } },
  ]) {
    const result = applyWorkspaceActivityStreamEvent(activities, event, 'workspace-1');
    assert.equal(result.handled, false);
    assert.equal(result.activities, activities);
  }
});

test('Desktop routes live workspace activities into the overview audit trail', () => {
  assert.match(appSource, /applyWorkspaceActivityStreamEvent\(/);
  assert.match(appSource, /workspaceActivityEventsHeadRef/);
  assert.match(appSource, /liveActivity=\{workspaceLiveActivity\}/);
  assert.match(overviewSource, /liveActivity = \[\]/);
  assert.match(overviewSource, /\[\.\.\.liveActivity, \.\.\.model\.recentActivity\]/);
});
