import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildSessionAgentTree, isSessionAgentTreeEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionAgentTreeModel.js'
);

const event = (id, type, payload, counter) => ({
  id,
  type,
  payload,
  eventTimeUs: 1_800_000_000 + counter,
  eventCounter: counter,
});

test('builds the Web-compatible Agent spawn tree with terminal state and communication evidence', () => {
  const model = buildSessionAgentTree([
    event(
      'spawn-coordinator',
      'agent_spawned',
      {
        agent_id: 'agent-coordinator',
        agent_name: 'Coordinator',
        child_session_id: 'conversation-coordinator',
        task_summary: 'Coordinate release verification',
      },
      1
    ),
    event(
      'spawn-reviewer',
      'agent_spawned',
      {
        agent_id: 'agent-reviewer',
        agent_name: 'Reviewer',
        parent_agent_id: 'agent-coordinator',
        child_session_id: 'conversation-reviewer',
        task_summary: 'Review the release evidence',
      },
      2
    ),
    event(
      'message-sent',
      'agent_message_sent',
      {
        from_agent_id: 'agent-coordinator',
        from_agent_name: 'Coordinator',
        to_agent_id: 'agent-reviewer',
        to_agent_name: 'Reviewer',
        message_preview: 'Verify all release gates',
      },
      3
    ),
    event(
      'message-received',
      'agent_message_received',
      {
        from_agent_id: 'agent-reviewer',
        from_agent_name: 'Reviewer',
        to_agent_id: 'agent-coordinator',
        to_agent_name: 'Coordinator',
        message_preview: 'All gates verified',
      },
      4
    ),
    event(
      'reviewer-complete',
      'agent_completed',
      {
        agent_id: 'agent-reviewer',
        session_id: 'conversation-reviewer',
        success: true,
        result: 'Release evidence approved',
        artifacts: ['release-report.md'],
      },
      5
    ),
    event(
      'coordinator-stopped',
      'agent_stopped',
      {
        agent_id: 'agent-coordinator',
        reason: 'Superseded by a newer run',
      },
      6
    ),
  ]);

  assert.deepEqual(model.summary, {
    total: 2,
    running: 0,
    completed: 1,
    failed: 0,
    stopped: 1,
    communications: 2,
  });
  assert.equal(model.roots.length, 1);
  assert.deepEqual(model.roots[0], {
    key: 'conversation-coordinator',
    agentId: 'agent-coordinator',
    name: 'Coordinator',
    parentAgentId: null,
    sessionId: 'conversation-coordinator',
    status: 'stopped',
    taskSummary: 'Coordinate release verification',
    result: null,
    stopReason: 'Superseded by a newer run',
    success: null,
    artifacts: [],
    createdAtUs: 1_800_000_001,
    lastUpdateAtUs: 1_800_000_006,
    children: [
      {
        key: 'conversation-reviewer',
        agentId: 'agent-reviewer',
        name: 'Reviewer',
        parentAgentId: 'agent-coordinator',
        sessionId: 'conversation-reviewer',
        status: 'completed',
        taskSummary: 'Review the release evidence',
        result: 'Release evidence approved',
        stopReason: null,
        success: true,
        artifacts: ['release-report.md'],
        createdAtUs: 1_800_000_002,
        lastUpdateAtUs: 1_800_000_005,
        children: [],
      },
    ],
  });
  assert.deepEqual(
    model.communications.map(({ type, fromLabel, toLabel, preview }) => ({
      type,
      fromLabel,
      toLabel,
      preview,
    })),
    [
      {
        type: 'sent',
        fromLabel: 'Coordinator',
        toLabel: 'Reviewer',
        preview: 'Verify all release gates',
      },
      {
        type: 'received',
        fromLabel: 'Reviewer',
        toLabel: 'Coordinator',
        preview: 'All gates verified',
      },
    ]
  );
});

test('fails closed for malformed and unrelated events without cross-linking identities', () => {
  const model = buildSessionAgentTree([
    event('missing-agent', 'agent_spawned', { agent_name: 'Guessed agent' }, 1),
    event('unknown-completion', 'agent_completed', { agent_id: 'agent-unknown' }, 2),
    event('message-without-endpoints', 'agent_message_sent', { message_preview: 'orphan' }, 3),
    event(
      'orphan-spawn',
      'agent_spawned',
      {
        agent_id: 'agent-orphan',
        agent_name: 'Orphan',
        parent_agent_id: 'agent-missing',
      },
      4
    ),
    event('unrelated', 'subagent_started', { agent_id: 'agent-orphan' }, 5),
  ]);

  assert.equal(model.summary.total, 1);
  assert.equal(model.roots.length, 1);
  assert.equal(model.roots[0].agentId, 'agent-orphan');
  assert.equal(model.roots[0].children.length, 0);
  assert.deepEqual(model.communications, []);
});

test('recognizes only the exact multi-Agent lifecycle protocol', () => {
  for (const type of [
    'agent_spawned',
    'agent_completed',
    'agent_stopped',
    'agent_message_sent',
    'agent_message_received',
  ]) {
    assert.equal(isSessionAgentTreeEvent({ type }), true);
  }
  assert.equal(isSessionAgentTreeEvent({ type: 'subagent_started' }), false);
  assert.equal(isSessionAgentTreeEvent({ type: 'agent_spawned_extra' }), false);
  assert.equal(isSessionAgentTreeEvent({ event_type: 'agent_spawned' }), true);
});

test('Desktop exposes the Agents canvas as a dynamic session surface with navigation', () => {
  const appSource = readFileSync(
    new URL('../src/App.tsx', import.meta.url),
    'utf8'
  );
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionAgentsCanvas.tsx', import.meta.url),
    'utf8'
  );
  const qaSource = readFileSync(
    new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url),
    'utf8'
  );

  assert.match(appSource, /buildSessionAgentTree\(timelineItems\)/);
  assert.match(appSource, /tab: 'agents'/);
  assert.match(appSource, /activeTab === 'agents'/);
  assert.match(appSource, /onOpenAgentSession/);
  assert.match(canvasSource, /session-agent-tree-canvas/);
  assert.match(canvasSource, /role="tree"/);
  assert.match(canvasSource, /onOpenSession\(sessionId\)/);
  assert.match(qaSource, /multi-agent-canvas/);
});
