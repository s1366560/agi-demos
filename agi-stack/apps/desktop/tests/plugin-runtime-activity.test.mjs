import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  pluginActionTimelineEntry,
  pluginCapabilityCountEntries,
  prependPluginActionTimeline,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/pluginManagementModel.js');
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const capabilityCounts = {
  channel_types: 2,
  tool_factories: 3,
  registered_tool_factories: 2,
  hooks: 4,
  commands: 5,
  services: 1,
  providers: 2,
};

const tracedResponse = {
  success: true,
  message: 'Plugin runtime reloaded.',
  details: {
    diagnostics: [
      { plugin_name: 'slack', code: 'optional_scope', message: 'Scope is optional.', level: 'info' },
    ],
    control_plane_trace: {
      trace_id: 'trace-reload-1',
      action: 'reload',
      plugin_name: null,
      requirement: null,
      tenant_id: 'tenant-a',
      timestamp: '2026-07-21T09:30:00.000Z',
      capability_counts: capabilityCounts,
    },
    channel_reload_plan: { reused: 1, restarted: 2 },
  },
};

test('plugin action timeline entries prefer authoritative control-plane trace fields', () => {
  assert.deepEqual(
    pluginActionTimelineEntry(tracedResponse, 'fallback', '2026-07-21T10:00:00.000Z'),
    {
      id: 'trace-reload-1',
      action: 'reload',
      message: 'Plugin runtime reloaded.',
      success: true,
      timestamp: '2026-07-21T09:30:00.000Z',
      details: tracedResponse.details,
    },
  );
  assert.deepEqual(
    pluginActionTimelineEntry(
      { success: false, message: 'Plugin action failed.' },
      'disable',
      '2026-07-21T10:00:00.000Z',
    ),
    {
      id: '2026-07-21T10:00:00.000Z:disable',
      action: 'disable',
      message: 'Plugin action failed.',
      success: false,
      timestamp: '2026-07-21T10:00:00.000Z',
      details: null,
    },
  );
});

test('plugin action timeline is newest first, deduplicated by trace, and capped at ten', () => {
  let timeline = [];
  for (let index = 0; index < 12; index += 1) {
    timeline = prependPluginActionTimeline(
      timeline,
      {
        success: true,
        message: `Action ${index}`,
        details: {
          control_plane_trace: {
            ...tracedResponse.details.control_plane_trace,
            trace_id: `trace-${index}`,
            timestamp: `2026-07-21T10:${String(index).padStart(2, '0')}:00.000Z`,
          },
        },
      },
      'reload',
      '2026-07-21T10:00:00.000Z',
    );
  }
  assert.equal(timeline.length, 10);
  assert.equal(timeline[0].id, 'trace-11');
  assert.equal(timeline.at(-1).id, 'trace-2');
  assert.equal(
    prependPluginActionTimeline(timeline, tracedResponse, 'reload', '2026-07-21T10:00:00.000Z')
      .filter((entry) => entry.id === 'trace-reload-1').length,
    1,
  );
});

test('plugin capability presentation preserves every server count in stable order', () => {
  assert.deepEqual(pluginCapabilityCountEntries(capabilityCounts), [
    ['channel_types', 2],
    ['tool_factories', 3],
    ['registered_tool_factories', 2],
    ['hooks', 4],
    ['commands', 5],
    ['services', 1],
    ['providers', 2],
  ]);
});

test('desktop plugin runtime API preserves diagnostics and typed action responses', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push([String(input), init?.method]);
    if (init?.method === 'POST') return Response.json(tracedResponse);
    return Response.json({
      items: [
        {
          name: 'slack',
          source: 'entrypoint',
          enabled: true,
          discovered: true,
          channel_types: ['slack'],
        },
      ],
      diagnostics: tracedResponse.details.diagnostics,
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant a',
    });
    const runtime = await client.getManagedPluginRuntime();
    const plugins = await client.listManagedPlugins();
    const response = await client.setManagedPluginEnabled('slack/events', false);

    assert.equal(runtime.items[0].id, 'slack');
    assert.deepEqual(runtime.diagnostics, tracedResponse.details.diagnostics);
    assert.equal(plugins[0].id, 'slack');
    assert.equal(response.details.control_plane_trace.trace_id, 'trace-reload-1');
    assert.deepEqual(calls, [
      ['http://127.0.0.1:8088/api/v1/channels/tenants/tenant%20a/plugins', 'GET'],
      ['http://127.0.0.1:8088/api/v1/channels/tenants/tenant%20a/plugins', 'GET'],
      [
        'http://127.0.0.1:8088/api/v1/channels/tenants/tenant%20a/plugins/slack%2Fevents/disable',
        'POST',
      ],
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
