import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildSessionExecutionGraph, isSessionExecutionGraphEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionExecutionGraphModel.js'
);

const event = (id, type, payload, counter) => ({
  id,
  type,
  payload,
  eventTimeUs: 1_900_000_000 + counter,
  eventCounter: counter,
});

test('builds the active Web-compatible execution DAG from run, node, and handoff events', () => {
  const model = buildSessionExecutionGraph([
    event(
      'run-started',
      'graph_run_started',
      {
        graph_run_id: 'run-release',
        graph_id: 'graph-release',
        graph_name: 'Release verification',
        pattern: 'supervisor',
        entry_node_ids: ['plan'],
      },
      1
    ),
    event(
      'plan-started',
      'graph_node_started',
      {
        graph_run_id: 'run-release',
        node_id: 'plan',
        node_label: 'Plan release checks',
        agent_definition_id: 'agent-planner',
        agent_session_id: 'conversation-planner',
      },
      2
    ),
    event(
      'plan-review-handoff',
      'graph_handoff',
      {
        graph_run_id: 'run-release',
        from_node_id: 'plan',
        to_node_id: 'review',
        from_label: 'Plan release checks',
        to_label: 'Review evidence',
        context_summary: 'Release plan ready for evidence review',
      },
      3
    ),
    event(
      'review-started',
      'graph_node_started',
      {
        graph_run_id: 'run-release',
        node_id: 'review',
        node_label: 'Review evidence',
        agent_definition_id: 'agent-reviewer',
        agent_session_id: 'conversation-reviewer',
      },
      4
    ),
    event(
      'plan-completed',
      'graph_node_completed',
      {
        graph_run_id: 'run-release',
        node_id: 'plan',
        node_label: 'Plan release checks',
        output_keys: ['release-plan.md'],
        duration_seconds: 2.5,
      },
      5
    ),
    event(
      'review-failed',
      'graph_node_failed',
      {
        graph_run_id: 'run-release',
        node_id: 'review',
        node_label: 'Review evidence',
        error_message: 'Evidence manifest is incomplete',
      },
      6
    ),
    event(
      'run-failed',
      'graph_run_failed',
      {
        graph_run_id: 'run-release',
        graph_id: 'graph-release',
        graph_name: 'Release verification',
        error_message: 'Evidence review failed',
        failed_node_id: 'review',
      },
      7
    ),
  ]);

  assert.equal(model.runs.length, 1);
  assert.equal(model.activeRun?.graphRunId, 'run-release');
  assert.deepEqual(model.summary, {
    runs: 1,
    nodes: 2,
    running: 0,
    completed: 1,
    failed: 1,
    skipped: 0,
    handoffs: 1,
  });
  assert.deepEqual(model.activeRun?.layers.map((layer) => layer.map((node) => node.nodeId)), [
    ['plan'],
    ['review'],
  ]);
  assert.deepEqual(model.activeRun?.nodes[0], {
    nodeId: 'plan',
    label: 'Plan release checks',
    agentDefinitionId: 'agent-planner',
    agentSessionId: 'conversation-planner',
    status: 'completed',
    outputKeys: ['release-plan.md'],
    errorMessage: null,
    skipReason: null,
    durationSeconds: 2.5,
    startedAtUs: 1_900_000_002,
    completedAtUs: 1_900_000_005,
  });
  assert.equal(model.activeRun?.nodes[1].status, 'failed');
  assert.equal(model.activeRun?.nodes[1].errorMessage, 'Evidence manifest is incomplete');
  assert.deepEqual(model.activeRun?.handoffs[0], {
    id: 'plan-review-handoff',
    fromNodeId: 'plan',
    toNodeId: 'review',
    fromLabel: 'Plan release checks',
    toLabel: 'Review evidence',
    contextSummary: 'Release plan ready for evidence review',
    eventTimeUs: 1_900_000_003,
  });
  assert.equal(model.activeRun?.status, 'failed');
  assert.equal(model.activeRun?.errorMessage, 'Evidence review failed');
  assert.equal(model.activeRun?.failedNodeId, 'review');
});

test('selects the latest run and preserves cancelled and skipped terminal states', () => {
  const model = buildSessionExecutionGraph([
    event(
      'older-run',
      'graph_run_started',
      {
        graph_run_id: 'run-older',
        graph_id: 'graph-older',
        graph_name: 'Older run',
        pattern: 'chain',
        entry_node_ids: [],
      },
      1
    ),
    event(
      'latest-run',
      'graph_run_started',
      {
        graph_run_id: 'run-latest',
        graph_id: 'graph-latest',
        graph_name: 'Latest run',
        pattern: 'swarm',
        entry_node_ids: ['worker'],
      },
      2
    ),
    event(
      'worker-started',
      'graph_node_started',
      {
        graph_run_id: 'run-latest',
        node_id: 'worker',
        node_label: 'Worker',
        agent_definition_id: 'agent-worker',
      },
      3
    ),
    event(
      'worker-skipped',
      'graph_node_skipped',
      {
        graph_run_id: 'run-latest',
        node_id: 'worker',
        node_label: 'Worker',
        reason: 'Dependency was cancelled',
      },
      4
    ),
    event(
      'latest-cancelled',
      'graph_run_cancelled',
      {
        graph_run_id: 'run-latest',
        graph_id: 'graph-latest',
        graph_name: 'Latest run',
        reason: 'Stopped by operator',
      },
      5
    ),
  ]);

  assert.deepEqual(model.runs.map((run) => run.graphRunId), ['run-latest', 'run-older']);
  assert.equal(model.activeRun?.status, 'cancelled');
  assert.equal(model.activeRun?.cancelReason, 'Stopped by operator');
  assert.equal(model.activeRun?.nodes[0].status, 'skipped');
  assert.equal(model.activeRun?.nodes[0].skipReason, 'Dependency was cancelled');
});

test('fails closed for malformed, duplicate, orphan, and unrelated events', () => {
  const model = buildSessionExecutionGraph([
    event('missing-run-id', 'graph_run_started', { graph_name: 'Guessed' }, 1),
    event(
      'valid-run',
      'graph_run_started',
      {
        graph_run_id: 'run-valid',
        graph_id: 'graph-valid',
        graph_name: 'Valid graph',
        pattern: 'chain',
        entry_node_ids: [],
      },
      2
    ),
    event('orphan-node', 'graph_node_started', { graph_run_id: 'run-missing' }, 3),
    event(
      'valid-node',
      'graph_node_started',
      {
        graph_run_id: 'run-valid',
        node_id: 'node-valid',
        node_label: 'Valid node',
        agent_definition_id: 'agent-valid',
      },
      4
    ),
    event(
      'valid-node',
      'graph_node_started',
      {
        graph_run_id: 'run-valid',
        node_id: 'node-duplicate',
        node_label: 'Duplicate event id',
        agent_definition_id: 'agent-duplicate',
      },
      5
    ),
    event('unrelated', 'agent_spawned', { graph_run_id: 'run-valid' }, 6),
  ]);

  assert.equal(model.runs.length, 1);
  assert.deepEqual(model.activeRun?.nodes.map((node) => node.nodeId), ['node-valid']);
  assert.deepEqual(model.activeRun?.handoffs, []);
});

test('recognizes only the exact graph orchestration protocol', () => {
  for (const type of [
    'graph_run_started',
    'graph_run_completed',
    'graph_run_failed',
    'graph_run_cancelled',
    'graph_node_started',
    'graph_node_completed',
    'graph_node_failed',
    'graph_node_skipped',
    'graph_handoff',
  ]) {
    assert.equal(isSessionExecutionGraphEvent({ type }), true);
  }
  assert.equal(isSessionExecutionGraphEvent({ type: 'graph_run_started_extra' }), false);
  assert.equal(isSessionExecutionGraphEvent({ type: 'agent_spawned' }), false);
  assert.equal(isSessionExecutionGraphEvent({ event_type: 'graph_handoff' }), true);
});

test('Desktop exposes a dynamic Graph canvas with node selection and session navigation', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionExecutionGraphCanvas.tsx', import.meta.url),
    'utf8'
  );
  const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

  assert.match(appSource, /buildSessionExecutionGraph\(timelineItems\)/);
  assert.match(appSource, /tab: 'graph'/);
  assert.match(appSource, /activeTab === 'graph'/);
  assert.match(canvasSource, /session-execution-graph-canvas/);
  assert.match(canvasSource, /aria-pressed=\{selected\}/);
  assert.match(canvasSource, /onOpenSession\(sessionId\)/);
  assert.match(qaSource, /execution-graph-canvas/);
});
