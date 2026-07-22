import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildSessionExecutionInsights, isSessionExecutionInsightEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionExecutionInsightsModel.js'
);

const event = (id, type, payload, counter) => ({
  id,
  type,
  payload,
  eventTimeUs: 1_900_000_000 + counter,
  eventCounter: counter,
});

test('builds one structured execution trace from routing, selection, policy, and toolset events', () => {
  const model = buildSessionExecutionInsights([
    event(
      'route',
      'execution_path_decided',
      {
        route_id: 'route-release',
        trace_id: 'trace-release',
        path: 'react_loop',
        confidence: 0.92,
        reason: 'Release verification requires governed tools',
        target: 'workspace-agent',
        metadata: { domain_lane: 'code' },
      },
      1
    ),
    event(
      'selection',
      'selection_trace',
      {
        route_id: 'route-release',
        trace_id: 'trace-release',
        domain_lane: 'code',
        initial_count: 12,
        final_count: 4,
        removed_total: 8,
        tool_budget: 4,
        budget_exceeded_stages: ['semantic_ranker'],
        stages: [
          {
            stage: 'capability_filter',
            before_count: 12,
            after_count: 7,
            removed_count: 5,
            duration_ms: 2.4,
            explain: { reason: 'Capability boundary' },
          },
          {
            stage: 'semantic_ranker',
            before_count: 7,
            after_count: 4,
            removed_count: 3,
            duration_ms: 5.8,
          },
        ],
      },
      2
    ),
    event(
      'policy',
      'policy_filtered',
      {
        route_id: 'route-release',
        trace_id: 'trace-release',
        domain_lane: 'code',
        removed_total: 3,
        stage_count: 2,
        tool_budget: 4,
        budget_exceeded_stages: ['semantic_ranker'],
      },
      3
    ),
    event(
      'toolset',
      'toolset_changed',
      {
        trace_id: 'trace-release',
        source: 'plugin_manager',
        action: 'install',
        plugin_name: 'github',
        refresh_status: 'success',
        refreshed_tool_count: 3,
        mutation_fingerprint: 'sha256:release',
      },
      4
    ),
  ]);

  assert.equal(model.traces.length, 1);
  assert.equal(model.activeTrace?.traceId, 'trace-release');
  assert.equal(model.activeTrace?.routeId, 'route-release');
  assert.equal(model.activeTrace?.domainLane, 'code');
  assert.deepEqual(model.summary, {
    traces: 1,
    entries: 4,
    routing: 1,
    selection: 1,
    policy: 1,
    toolset: 1,
    warnings: 2,
  });
  assert.deepEqual(model.activeTrace?.entries.map((entry) => entry.stage), [
    'routing',
    'selection',
    'policy',
    'toolset',
  ]);
  assert.deepEqual(model.activeTrace?.entries[0].routing, {
    path: 'react_loop',
    confidence: 0.92,
    reason: 'Release verification requires governed tools',
    target: 'workspace-agent',
  });
  assert.deepEqual(model.activeTrace?.entries[1].selection?.stages, [
    {
      name: 'capability_filter',
      beforeCount: 12,
      afterCount: 7,
      removedCount: 5,
      durationMs: 2.4,
      explanation: { reason: 'Capability boundary' },
    },
    {
      name: 'semantic_ranker',
      beforeCount: 7,
      afterCount: 4,
      removedCount: 3,
      durationMs: 5.8,
      explanation: null,
    },
  ]);
  assert.equal(model.activeTrace?.entries[2].policy?.removedTotal, 3);
  assert.deepEqual(model.activeTrace?.entries[3].toolset, {
    updateKind: 'toolset_changed',
    source: 'plugin_manager',
    action: 'install',
    pluginName: 'github',
    refreshStatus: 'success',
    refreshedToolCount: 3,
    mutationFingerprint: 'sha256:release',
    serverName: null,
    toolNames: [],
    requiresRefresh: null,
  });
});

test('selects the latest trace and keeps identity-less diagnostics isolated', () => {
  const model = buildSessionExecutionInsights([
    event(
      'older-route',
      'execution_path_decided',
      { trace_id: 'trace-old', path: 'direct_skill', confidence: 0.8, reason: 'Skill matched' },
      1
    ),
    event(
      'singleton-toolset',
      'toolset_changed',
      { source: 'filesystem', action: 'reload', refresh_status: 'deferred' },
      2
    ),
    event(
      'latest-route',
      'execution_path_decided',
      { route_id: 'route-latest', path: 'plan_mode', confidence: 0.7, reason: 'Plan requested' },
      3
    ),
  ]);

  assert.equal(model.traces.length, 3);
  assert.equal(model.activeTrace?.routeId, 'route-latest');
  assert.deepEqual(model.traces.map((trace) => trace.groupKey), [
    'route:route-latest',
    'event:singleton-toolset',
    'trace:trace-old',
  ]);
  assert.equal(model.traces[1].entries[0].toolset?.refreshStatus, 'deferred');
});

test('projects tools_updated as structured MCP registry evidence', () => {
  const model = buildSessionExecutionInsights([
    event(
      'registry-update',
      'tools_updated',
      {
        project_id: 'project-release',
        server_name: 'release-tools',
        tool_names: ['mcp__release__verify', 'mcp__release__publish'],
        requires_refresh: true,
      },
      1
    ),
  ]);

  assert.equal(model.traces.length, 1);
  assert.deepEqual(model.summary, {
    traces: 1,
    entries: 1,
    routing: 0,
    selection: 0,
    policy: 0,
    toolset: 1,
    warnings: 0,
  });
  assert.deepEqual(model.activeTrace?.entries[0].toolset, {
    updateKind: 'tools_updated',
    source: null,
    action: null,
    pluginName: null,
    refreshStatus: null,
    refreshedToolCount: null,
    mutationFingerprint: null,
    serverName: 'release-tools',
    toolNames: ['mcp__release__verify', 'mcp__release__publish'],
    requiresRefresh: true,
  });
});

test('fails closed for malformed, duplicate, and unrelated diagnostics', () => {
  const model = buildSessionExecutionInsights([
    event('bad-route', 'execution_path_decided', { path: 'react_loop', confidence: 'high' }, 1),
    event(
      'valid-route',
      'execution_path_decided',
      { trace_id: 'trace-valid', path: 'react_loop', confidence: 0.9, reason: 'Tools required' },
      2
    ),
    event(
      'valid-route',
      'execution_path_decided',
      { trace_id: 'trace-valid', path: 'duplicate', confidence: 0.1, reason: 'Duplicate id' },
      3
    ),
    event(
      'bad-selection',
      'selection_trace',
      {
        trace_id: 'trace-valid',
        initial_count: 8,
        final_count: 3,
        removed_total: 5,
        stages: [{ stage: 'rank', before_count: 8 }],
      },
      4
    ),
    event(
      'bad-policy',
      'policy_filtered',
      { trace_id: 'trace-valid', removed_total: -1, stage_count: 1 },
      5
    ),
    event(
      'bad-toolset',
      'toolset_changed',
      { trace_id: 'trace-valid', source: 'plugin_manager', refresh_status: 'invented' },
      6
    ),
    event(
      'bad-registry-update',
      'tools_updated',
      {
        server_name: 'release-tools',
        tool_names: ['mcp__release__verify'],
        requires_refresh: 'yes',
      },
      7
    ),
    event('unrelated', 'skill_matched', { trace_id: 'trace-valid' }, 8),
  ]);

  assert.equal(model.traces.length, 1);
  assert.deepEqual(model.activeTrace?.entries.map((entry) => entry.id), ['valid-route']);
});

test('recognizes only the exact execution insight protocol', () => {
  for (const type of [
    'execution_path_decided',
    'selection_trace',
    'policy_filtered',
    'toolset_changed',
    'tools_updated',
  ]) {
    assert.equal(isSessionExecutionInsightEvent({ type }), true);
  }
  assert.equal(isSessionExecutionInsightEvent({ type: 'execution_path_decided_extra' }), false);
  assert.equal(isSessionExecutionInsightEvent({ type: 'tool_policy_denied' }), false);
  assert.equal(isSessionExecutionInsightEvent({ event_type: 'selection_trace' }), true);
});

test('Desktop exposes a dynamic Insights canvas with selectable diagnostic evidence', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionExecutionInsightsCanvas.tsx', import.meta.url),
    'utf8'
  );
  const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

  assert.match(appSource, /buildSessionExecutionInsights\(timelineItems\)/);
  assert.match(appSource, /tab: 'insights'/);
  assert.match(appSource, /activeTab === 'insights'/);
  assert.match(canvasSource, /session-execution-insights-canvas/);
  assert.match(canvasSource, /aria-pressed=\{selected\}/);
  assert.match(canvasSource, /selection\.stages\.map/);
  assert.match(canvasSource, /entry\.toolset\.toolNames\.join/);
  assert.match(canvasSource, /entry\.toolset\.requiresRefresh/);
  assert.match(qaSource, /execution-insights-canvas/);
  assert.match(qaSource, /insights-release-tools-updated/);
});
